export default function PurpleBadge({ score, verdict }:
  { score: number | null; verdict: string | null }) {
  if (score === null) return <div className="badge s0">–<small>미진단</small></div>
  return (
    <div className={`badge s${score}`} title={verdict ?? ''}>
      {score}<small>{verdict}</small>
    </div>
  )
}
