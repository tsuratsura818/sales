import coreWebVitals from 'eslint-config-next/core-web-vitals'
import nextTypescript from 'eslint-config-next/typescript'

const config = [
  ...coreWebVitals,
  ...nextTypescript,
  { ignores: ['.next/**', 'node_modules/**', 'src/types/database.ts'] },
]

export default config
