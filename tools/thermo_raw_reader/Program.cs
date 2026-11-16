using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Globalization;
using ThermoFisher.CommonCore.Data.Business;
using ThermoFisher.CommonCore.RawFileReader;

// Spectrum mode writes only SCMMRAW1; --acquisition writes one metadata JSON.
bool acquisition = args.Length == 2 && args[0] == "--acquisition";
if (args.Length != 1 && !acquisition)
{
    Console.Error.WriteLine("Usage: scmm-thermo-reader [--acquisition] file.raw");
    return 2;
}
try
{
    if (!BitConverter.IsLittleEndian)
        throw new PlatformNotSupportedException("Little-endian platform required");
    var filename = args[^1];
    if (!File.Exists(filename)) throw new FileNotFoundException(filename);
    using var raw = RawFileReaderAdapter.FileFactory(filename);
    if (!raw.IsOpen || raw.IsError) throw new IOException("Cannot open RAW file");
    if (raw.InAcquisition) throw new IOException("RAW file is still in acquisition");
    // The vendor default omits reference/exception peaks. Preserve all data,
    // matching ProteoWizard's Thermo reader (this is not a processing filter).
    raw.IncludeReferenceAndExceptionData = true;
    raw.SelectInstrument(Device.MS, 1);
    var header = raw.RunHeaderEx;
    if (header.SpectraCount <= 0) throw new InvalidDataException("RAW contains no MS spectra");
    if (acquisition)
    {
        var windows = new List<double[]>();
        var resolutions = new SortedSet<double>();
        var records = new List<object>();
        int inspected = 0;
        for (int number = header.FirstSpectrum; number <= header.LastSpectrum && inspected < 32; number++)
        {
            var filter = raw.GetFilterForScanNumber(number);
            if ((int)filter.MSOrder != 1) continue;
            if (raw.GetScanStatsForScanNumber(number).IsCentroidScan)
                throw new InvalidDataException($"Scan {number} is centroid, not profile");
            inspected++;
            for (int j = 0; j < filter.MassRangeCount; j++)
            {
                var range = filter.GetMassRange(j);
                if (double.IsFinite(range.Low) && double.IsFinite(range.High) && range.Low > 0 && range.High > range.Low)
                    windows.Add(new[] { range.Low, range.High });
            }
            var trailer = raw.GetTrailerExtraInformation(number);
            for (int j = 0; j < trailer.Labels.Length; j++)
            {
                string label = trailer.Labels[j];
                string key = label.Trim().TrimEnd(':').Trim();
                if (!new[] { "FT Resolution", "Orbitrap Resolution", "Resolution" }.Contains(key, StringComparer.OrdinalIgnoreCase)) continue;
                string value = trailer.Values[j];
                records.Add(new { scan = number, label, value });
                if (double.TryParse(value, NumberStyles.Float | NumberStyles.AllowThousands,
                    CultureInfo.InvariantCulture, out double resolution) && double.IsFinite(resolution) && resolution > 0)
                    resolutions.Add(resolution);
            }
        }
        Console.Write(JsonSerializer.Serialize(new {
            schema_version = 1,
            windows = windows.DistinctBy(v => (v[0], v[1])).ToArray(),
            resolutions = resolutions.ToArray(),
            resolution_records = records,
            ms1_scans_inspected = inspected,
            note = "读取前 32 个 MS1 扫描的采集质量窗与分辨率附加记录；分辨率参考质量未经确认，请核对后手动填写。"
        }));
        return 0;
    }
    using var output = new BufferedStream(Console.OpenStandardOutput(), 65536);
    using var writer = new BinaryWriter(output, Encoding.UTF8, leaveOpen: true);
    writer.Write(Encoding.ASCII.GetBytes("SCMMRAW1"));
    writer.Write(header.SpectraCount);
    // Unspecified vendor wall-clock time: do not invent a UTC offset.
    WriteText(writer, raw.FileHeader.CreationDate.ToString("yyyy-MM-ddTHH:mm:ss.fffffff",
        System.Globalization.CultureInfo.InvariantCulture));
    WriteText(writer, raw.GetInstrumentData().Model ?? "");
    int scans = 0;
    long points = 0;
    for (int number = header.FirstSpectrum; number <= header.LastSpectrum; number++)
    {
        var stats = raw.GetScanStatsForScanNumber(number);
        if (stats.IsCentroidScan)
            throw new InvalidDataException($"Scan {number} is centroid, not profile; no scans are skipped");
        var level = (int)raw.GetFilterForScanNumber(number).MSOrder;
        if (level < 1) throw new InvalidDataException($"Unsupported MS order at scan {number}");
        var scan = raw.GetSegmentedScanFromScanNumber(number, null);
        if (scan.Positions.Length != scan.Intensities.Length)
            throw new InvalidDataException($"Array length mismatch at scan {number}");
        writer.Write((byte)1);
        writer.Write(number);
        writer.Write(level);
        writer.Write((byte)1); // profile
        writer.Write(raw.RetentionTimeFromScanNumber(number) * 60.0);
        writer.Write(scan.Positions.Length);
        writer.Write(MemoryMarshal.AsBytes(scan.Positions.AsSpan()));
        writer.Write(MemoryMarshal.AsBytes(scan.Intensities.AsSpan()));
        scans++;
        points += scan.Positions.Length;
    }
    if (scans != header.SpectraCount) throw new InvalidDataException("Scan count mismatch");
    writer.Write((byte)0);
    writer.Write(scans);
    writer.Write(points);
    writer.Flush();
    return 0;
}
catch (Exception error)
{
    Console.Error.WriteLine($"Thermo RAW read failed: {error.Message}");
    return 1;
}

static void WriteText(BinaryWriter writer, string value)
{
    var bytes = Encoding.UTF8.GetBytes(value);
    writer.Write(bytes.Length);
    writer.Write(bytes);
}
