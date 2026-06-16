// Future agents: continue building the OpenProject adapter boundary in this
// file. Put client, mapper, and raw schema details in the sibling files already
// defined by SPEC.md.

import type { ProjectSystemAdapter } from "../project-system-adapter";

export interface OpenProjectAdapterConfig {
  readonly base_url: string;
  readonly source_instance?: string;
  readonly api_token_env_var?: string;
}

export interface OpenProjectAdapter extends ProjectSystemAdapter {
  readonly source_system: "openproject";
  readonly config: OpenProjectAdapterConfig;
}
