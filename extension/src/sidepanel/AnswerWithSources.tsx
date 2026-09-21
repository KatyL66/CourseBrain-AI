import type { SourceReference } from "../shared/types";

const SOURCE_REF_PATTERN = /\[SOURCE\s+(\d+)[^\]]*\]/gi;

interface Props {
  answer: string;
  references: SourceReference[];
  onOpenSource: (ref: SourceReference) => void;
}

function refByRank(refs: SourceReference[]): Map<number, SourceReference> {
  const map = new Map<number, SourceReference>();
  for (const ref of refs) {
    map.set(ref.rank, ref);
  }
  return map;
}

export function AnswerWithSources({ answer, references, onOpenSource }: Props) {
  const refMap = refByRank(references);
  const parts: Array<{ type: "text"; value: string } | { type: "source"; rank: number; raw: string }> = [];

  let lastIndex = 0;
  for (const match of answer.matchAll(SOURCE_REF_PATTERN)) {
    const index = match.index ?? 0;
    if (index > lastIndex) {
      parts.push({ type: "text", value: answer.slice(lastIndex, index) });
    }
    parts.push({ type: "source", rank: Number(match[1]), raw: match[0] });
    lastIndex = index + match[0].length;
  }
  if (lastIndex < answer.length) {
    parts.push({ type: "text", value: answer.slice(lastIndex) });
  }
  if (parts.length === 0) {
    parts.push({ type: "text", value: answer });
  }

  return (
    <div className="answer-text">
      {parts.map((part, i) => {
        if (part.type === "text") {
          return <span key={i}>{part.value}</span>;
        }

        const ref = refMap.get(part.rank);
        if (!ref) {
          return (
            <span key={i} className="source-ref-missing">
              {part.raw}
            </span>
          );
        }

        return (
          <button
            key={i}
            type="button"
            className="source-ref-chip"
            onClick={() => onOpenSource(ref)}
            title={`打开 ${ref.label}`}
          >
            📄 {ref.label} ↗
          </button>
        );
      })}
    </div>
  );
}
