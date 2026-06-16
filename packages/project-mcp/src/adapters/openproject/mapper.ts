// Future agents: implement OpenProject-to-contract mapping in this file. Do
// not create another OpenProject mapper file unless SPEC.md is updated first.

import type { ProjectRef, WorkItemRef } from "@formoowl/contract";
import type { ProjectStatusSummary, ProjectWorkItem, WorkItemActivity, WorkItemRelation } from "../../types";
import type { OpenProjectRawActivity, OpenProjectRawProject, OpenProjectRawRelation, OpenProjectRawWorkPackage } from "./schemas";

export interface OpenProjectMapper {
  to_project_ref(raw: OpenProjectRawProject): ProjectRef;
  to_work_item_ref(raw: OpenProjectRawWorkPackage): WorkItemRef;
  to_work_item(raw: OpenProjectRawWorkPackage): ProjectWorkItem;
  to_activity(raw: OpenProjectRawActivity): WorkItemActivity;
  to_relation(raw: OpenProjectRawRelation): WorkItemRelation;
  to_project_status(raw: OpenProjectRawProject): ProjectStatusSummary;
}
