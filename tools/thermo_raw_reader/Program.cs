using System.Runtime.InteropServices;
using System.Text;
using ThermoFisher.CommonCore.Data.Business;
using ThermoFisher.CommonCore.RawFileReader;

// stdout is exclusively SCMMRAW1 binary. Never add Console.WriteLine here.
if (args.Length != 1)
{
    Console.Error.WriteLine("Usage: scmm-thermo-reader file.raw");
    return 2;
}
try
{
    if (!BitConverter.IsLittleEndian)
        throw new PlatformNotSupportedException("Little-endian platform required");
    if (!File.Exists(args[0])) throw new FileNotFoundException(args[0]);
    using var raw = RawFileReaderAdapter.FileFactory(args[0]);
    if (!raw.IsOpen || raw.IsError) throw new IOException("Cannot open RAW file");
    if (raw.InAcquisition) throw new IOException("RAW file is still in acquisition");
    // The vendor default omits reference/exception peaks. Preserve all data,
    // matching ProteoWizard's Thermo reader (this is not a processing filter).
    raw.IncludeReferenceAndExceptionData = true;
    raw.SelectInstrument(Device.MS, 1);
    var header = raw.RunHeaderEx;
    if (header.SpectraCount <= 0) throw new InvalidDataException("RAW contains no MS spectra");
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
