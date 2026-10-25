import React, { useEffect, useState } from "react";

interface ServiceHealth {
  status: string;
  [key: string]: unknown;
}

interface HealthResponse {
  status: string;
  timestamp: string;
  services: {
    mongodb: ServiceHealth;
    gridfs: ServiceHealth;
  };
}

export const App: React.FC = () => {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  const fetchHealth = async () => {
    setLoading(true);
    setError(null);
    try {
      const apiUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";
      const res = await fetch(`${apiUrl}/health`);
      if (!res.ok) {
        throw new Error(`HTTP ${res.status} ${res.statusText}`);
      }
      const data: HealthResponse = await res.json();
      setHealth(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to fetch health check");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchHealth();
  }, []);

  return (
    <main className="p-8 max-w-3xl mx-auto space-y-6">
      {/* Intended-use notice strip */}
      <section
        role="region"
        aria-label="Intended use notice"
        className="p-4 border border-[#D5DAD8] bg-white text-sm leading-relaxed"
      >
        <p className="font-semibold text-[#18242C] mb-1">Intended Use Statement</p>
        <p className="text-[#18242C]">
          ONCOLINK is a research and education prototype. It is not a medical device, does not
          diagnose cancer, and must not be used for clinical decisions. Only a biopsy can confirm
          oral cancer. All data comes from public datasets and consenting volunteers.
        </p>
      </section>

      {/* Foundation Verification Panel */}
      <section className="p-6 border border-[#D5DAD8] bg-white space-y-4">
        <h1 className="text-xl font-semibold text-[#18242C]">ONCOLINK Foundation Health Check</h1>

        <div>
          <button
            type="button"
            onClick={() => void fetchHealth()}
            className="px-4 py-2 bg-[#4B2E83] text-white text-sm font-medium hover:bg-[#3d246c] focus:outline-none focus:ring-2 focus:ring-[#4B2E83] focus:ring-offset-2"
          >
            Refresh Health Status
          </button>
        </div>

        {loading && <p className="text-sm text-[#18242C]">Checking backend health...</p>}

        {error && (
          <div className="p-3 border border-[#B42318] bg-red-50 text-[#B42318] text-sm">
            Failed to connect to backend: {error}
          </div>
        )}

        {health && (
          <div className="space-y-3">
            <div className="text-sm">
              <span className="font-medium">System Status: </span>
              <span
                className={
                  health.status === "healthy"
                    ? "font-semibold text-[#2F7D57]"
                    : "font-semibold text-[#B42318]"
                }
              >
                {health.status.toUpperCase()}
              </span>
            </div>

            <table className="w-full text-left text-sm border-collapse border border-[#D5DAD8]">
              <thead>
                <tr className="bg-[#F5F7F6] border-b border-[#D5DAD8]">
                  <th className="p-2 border-r border-[#D5DAD8]">Service</th>
                  <th className="p-2 border-r border-[#D5DAD8]">Status</th>
                  <th className="p-2">Details</th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-b border-[#D5DAD8]">
                  <td className="p-2 font-medium border-r border-[#D5DAD8]">MongoDB</td>
                  <td className="p-2 border-r border-[#D5DAD8]">
                    {String(health.services.mongodb.status)}
                  </td>
                  <td className="p-2 text-xs">
                    Replica Set: {String(health.services.mongodb.replica_set ?? "N/A")}
                  </td>
                </tr>
                <tr>
                  <td className="p-2 font-medium border-r border-[#D5DAD8]">GridFS Storage</td>
                  <td className="p-2 border-r border-[#D5DAD8]">
                    {String(health.services.gridfs.status)}
                  </td>
                  <td className="p-2 text-xs">
                    Bucket: {String(health.services.gridfs.bucket ?? "N/A")}
                  </td>
                </tr>
              </tbody>
            </table>

            <p className="text-xs text-gray-500">Last Checked: {health.timestamp}</p>
          </div>
        )}
      </section>
    </main>
  );
};

export default App;
