import type { ActionRequest } from "./types";

export function authorizationLabel(action: ActionRequest): string {
  if (action.authorization) {
    return { approve: "Approved", reject: "Rejected", expired: "Expired" }[action.authorization.decision];
  }
  return action.status === "pending" ? "Pending review" : "Authorization unknown";
}
