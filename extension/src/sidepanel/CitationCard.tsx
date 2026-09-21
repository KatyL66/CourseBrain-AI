import type { Citation } from "../shared/types";

interface Props {
  citation: Citation;
  onOpen: (url: string, excerpt: string, page?: number) => void;
  showScore?: boolean;
}

function formatScore(score?: number): string | null {
  if (score == null) return null;
  return `${Math.round(score * 100)}%`;
}

export function CitationCard({ citation, onOpen, showScore = false }: Props) {
  const scoreLabel = formatScore(citation.score);
  const title = citation.topic_title || "未知来源";

  return (
    <div className="citation">
      <div className="citation-head">
        {citation.rank != null && (
          <span className="citation-rank">#{citation.rank}</span>
        )}
        <div className="citation-meta">
          <strong>{title}</strong>
          <div className="citation-tags">
            {citation.module && <span className="citation-tag">{citation.module}</span>}
            {citation.page != null && (
              <span className="citation-tag">第 {citation.page} 页</span>
            )}
            {showScore && scoreLabel && (
              <span className="citation-tag score">相关度 {scoreLabel}</span>
            )}
          </div>
        </div>
      </div>
      <p className="citation-excerpt">{citation.excerpt}…</p>
      <button
        className="btn small"
        onClick={() => onOpen(citation.url, citation.excerpt, citation.page)}
      >
        打开并定位
      </button>
    </div>
  );
}
