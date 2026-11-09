import ReportsPage from "./ReportsPage.jsx";

export default function ReportsAnalysisPage({ client }) {
  return (
    <div className="stack">
      <p className="hint" style={{ margin: 0 }}>
        Maak en rond rapporten af. Analyse gebruikt <strong>opgeslagen</strong> klantdata — niet
        Synchroniseer Meta. Beeldanalyse zit bij de post onder Media &amp; insight; AI Trial onder
        Settings → AI Connections.
      </p>
      <ReportsPage key={`reports-${client.id}`} client={client} />
    </div>
  );
}
