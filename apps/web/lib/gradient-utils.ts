export const GRADIENT_PRESETS = [
  'from-violet-600 via-purple-600 to-fuchsia-500',
  'from-blue-600 via-indigo-600 to-violet-500',
  'from-emerald-600 via-teal-600 to-cyan-500',
  'from-orange-500 via-amber-500 to-yellow-500',
  'from-rose-600 via-pink-600 to-fuchsia-500',
  'from-cyan-500 via-blue-500 to-indigo-500',
  'from-sky-500 via-cyan-400 to-teal-400',
  'from-pink-500 via-rose-500 to-orange-400',
]

/**
 * A deep shade of each preset, in the same order, for the band a project's
 * name sits on under its gradient. Dark enough for white text on every one.
 */
export const GRADIENT_BAND_COLOURS = [
  '#5b21b6', // violet-800
  '#3730a3', // indigo-800
  '#115e59', // teal-800
  '#9a3412', // orange-800
  '#9f1239', // rose-800
  '#1e40af', // blue-800
  '#155e75', // cyan-800
  '#be123c', // rose-700
]

function presetIndex(projectId: string): number {
  const hash = projectId.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0)
  return hash % GRADIENT_PRESETS.length
}

export function getGradientForProject(projectId: string): string {
  return GRADIENT_PRESETS[presetIndex(projectId)]
}

/** The band colour that goes with the gradient `getGradientForProject` picks. */
export function getBandColourForProject(projectId: string): string {
  return GRADIENT_BAND_COLOURS[presetIndex(projectId)]
}
