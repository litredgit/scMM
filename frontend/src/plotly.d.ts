declare module 'plotly.js-dist-min' {
  const Plotly: {
    react: (
      element: HTMLElement,
      data: unknown[],
      layout: Record<string, unknown>,
      config: Record<string, unknown>,
    ) => Promise<unknown>
    purge: (element: HTMLElement) => void
    Plots: { resize: (element: HTMLElement) => void }
    downloadImage: (element: HTMLElement, options: Record<string, unknown>) => Promise<unknown>
    newPlot: (
      element: HTMLElement,
      data: unknown[],
      layout: Record<string, unknown>,
      config: Record<string, unknown>,
    ) => Promise<unknown>
    toImage: (element: HTMLElement, options: Record<string, unknown>) => Promise<string>
  }
  export default Plotly
}
