import { flow } from "@agent-flow/core";

const raw = await flow.exec({ command: "curl", args: ["{{url}}"] });
const transformed = await flow.session({
  prompt: `Transform this data to JSON: ${raw.stdout}`
});
await flow.exec({ command: "bash", args: ["-c", `echo '${transformed}' > output.json`] });
