// Future agents: implement the OpenProject API client in this file. Do not
// create another OpenProject client file unless SPEC.md is updated first.

import type { JsonValue } from "@formoowl/contract";
import type { OpenProjectAdapterConfig } from "./openproject-adapter";

export abstract class OpenProjectClient {
  abstract readonly config: OpenProjectAdapterConfig;

  abstract request(path: string, init?: JsonValue): Promise<JsonValue>;
}
