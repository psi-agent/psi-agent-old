import { flow } from "@agent-flow/core";

const result = await flow.parallel([
  flow.session({ prompt: "Research topic A" }),
  flow.session({ prompt: "Research topic B" }),
  flow.session({ prompt: "Research topic C" }),
]).then(results => flow.session({
  prompt: `Synthesize: ${results.join("\n")}`
}));
