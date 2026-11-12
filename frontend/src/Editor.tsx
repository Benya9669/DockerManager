import { useTheme } from "./ui";
import CodeMirror from "@uiw/react-codemirror";
import { yaml } from "@codemirror/lang-yaml";
import { json } from "@codemirror/lang-json";

function langFor(filename: string) {
  const f = filename.toLowerCase();
  if (f.endsWith(".yml") || f.endsWith(".yaml")) return [yaml()];
  if (f.endsWith(".json")) return [json()];
  return [];
}

export function Editor({
  value, onChange, filename = "", readOnly, height = "60vh",
}: { value: string; onChange?: (v: string) => void; filename?: string; readOnly?: boolean; height?: string }) {
  return (
    <CodeMirror
      value={value}
      onChange={onChange}
      theme={useTheme()}
      height={height}
      readOnly={readOnly}
      extensions={langFor(filename)}
      basicSetup={{ lineNumbers: true, foldGutter: true, highlightActiveLine: !readOnly }}
    />
  );
}
