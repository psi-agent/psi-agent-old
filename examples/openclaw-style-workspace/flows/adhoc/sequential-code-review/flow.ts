import { flow } from "@agent-flow/core";

const reviewed = await flow.session({
  prompt: "Review this code for security issues: {{code}}"
});
const fixed = await flow.session({
  prompt: `Fix these issues: ${reviewed}`
});
