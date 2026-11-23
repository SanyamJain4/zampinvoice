/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend base URL for split deployments (no trailing slash). Leave unset for same-origin. */
  readonly VITE_API_URL?: string
}
interface ImportMeta {
  readonly env: ImportMetaEnv
}
