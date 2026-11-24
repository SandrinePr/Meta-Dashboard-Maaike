import ReportsPage from "./ReportsPage.jsx";

export default function ReportsAnalysisPage({
  client,
  onOpenStrategy,
  onOpenFigmaPlanning,
  onOpenSocialPosts,
  onOpenSettings,
}) {
  return (
    <div className="stack">
      <ReportsPage
        key={`reports-${client.id}`}
        client={client}
        onOpenStrategy={onOpenStrategy}
        onOpenFigmaPlanning={onOpenFigmaPlanning}
        onOpenSocialPosts={onOpenSocialPosts}
        onOpenSettings={onOpenSettings}
      />
    </div>
  );
}
