import ReportsPage from "./ReportsPage.jsx";

export default function ReportsAnalysisPage({
  client,
  role = "viewer",
  canEdit = false,
  canTechAdmin = false,
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
        role={role}
        canEdit={canEdit}
        canTechAdmin={canTechAdmin}
        onOpenStrategy={onOpenStrategy}
        onOpenFigmaPlanning={onOpenFigmaPlanning}
        onOpenSocialPosts={onOpenSocialPosts}
        onOpenSettings={onOpenSettings}
      />
    </div>
  );
}
