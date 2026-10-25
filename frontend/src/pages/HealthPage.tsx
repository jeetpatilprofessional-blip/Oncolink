import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AuditLine, Banner, Button, DataTable, StatusMarker, type Column } from "../components";
import { t } from "../locales/i18n";

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

interface ServiceRow extends Record<string, unknown> {
  name: string;
  status: "routine" | "urgent";
  statusText: string;
  details: string;
}

export const HealthPage: React.FC = () => {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [lastCheckedTime, setLastCheckedTime] = useState<string>("—");

  const fetchHealth = async () => {
    setLoading(true);
    setError(null);
    try {
      const apiUrl = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
      // Fetch health details endpoint which includes subsystem status
      const res = await fetch(`${apiUrl}/health/details`).catch(() => fetch(`${apiUrl}/health`));
      if (!res.ok) {
        throw new Error(`HTTP ${res.status} ${res.statusText}`);
      }
      const data: HealthResponse = await res.json();
      setHealth(data);
      const date = data.timestamp ? new Date(data.timestamp) : new Date();
      const hours = String(date.getHours()).padStart(2, "0");
      const minutes = String(date.getMinutes()).padStart(2, "0");
      setLastCheckedTime(`${hours}:${minutes}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to fetch health check");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchHealth();
  }, []);

  const serviceRows: ServiceRow[] = health?.services
    ? [
        {
          name: "MongoDB Database",
          status: health.services.mongodb?.status === "connected" ? "routine" : "urgent",
          statusText: String(health.services.mongodb?.status ?? "unknown"),
          details: `Replica Set: ${String(health.services.mongodb?.replica_set ?? "rs0")}`,
        },
        {
          name: "GridFS Storage",
          status: health.services.gridfs?.status === "connected" ? "routine" : "urgent",
          statusText: String(health.services.gridfs?.status ?? "unknown"),
          details: `Bucket: ${String(health.services.gridfs?.bucket ?? "case_images")}, File count: ${String(
            health.services.gridfs?.file_count ?? "0"
          )}`,
        },
      ]
    : health
      ? [
          {
            name: "Backend Service",
            status: health.status === "healthy" ? "routine" : "urgent",
            statusText: String(health.status),
            details: "API operational",
          },
        ]
      : [];

  const columns: Column<ServiceRow>[] = [
    { key: "name", header: t("table.service"), sortable: true },
    {
      key: "status",
      header: t("table.status"),
      sortable: true,
      render: (row) => <StatusMarker urgency={row.status} aria-label={row.statusText} />,
    },
    { key: "details", header: t("table.details"), sortable: false },
  ];

  return (
    <div className="min-h-screen bg-[#F5F7F6] text-[#18242C] font-sans pb-12">
      {/* 1. Intended-Use Notice Banner */}
      <Banner />

      <main className="max-w-3xl mx-auto px-4 py-8 space-y-6 text-left">
        <header className="flex flex-wrap items-baseline justify-between gap-4 border-b border-[#D5DAD8] pb-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-[#18242C]">
              ONCOLINK Foundation Health Check
            </h1>
            <p className="text-sm text-[#18242C]/70 mt-1">
              Verifying local MongoDB replica set connection and GridFS image storage.
            </p>
          </div>
          {import.meta.env.DEV && (
            <Link
              to="/dev/components"
              className="text-xs font-medium text-[#4B2E83] underline hover:text-[#3d246c] focus-visible:outline-2 focus-visible:outline-[#4B2E83]"
            >
              Open Components Gallery →
            </Link>
          )}
        </header>

        <div>
          <Button variant="primary" onClick={() => void fetchHealth()} disabled={loading}>
            {loading ? "Checking status..." : t("actions.refresh_health")}
          </Button>
        </div>

        {error && (
          <div
            role="alert"
            className="p-3 border-l-4 border-[#B42318] bg-white border border-[#D5DAD8] text-sm text-[#18242C]"
          >
            <span className="font-semibold text-[#B42318]">Connection error: </span>
            {error}
          </div>
        )}

        {health && (
          <section aria-labelledby="status-overview" className="space-y-4">
            <div className="flex items-center gap-3 p-4 bg-white border border-[#D5DAD8]">
              <span id="status-overview" className="text-sm font-semibold">
                {t("common.system_status")}:
              </span>
              <StatusMarker urgency={health.status === "healthy" ? "routine" : "urgent"} />
              <span className="text-xs text-[#18242C]/60 tabular-nums ml-auto">
                {t("common.last_checked")}: {lastCheckedTime}
              </span>
            </div>

            <DataTable
              columns={columns}
              data={serviceRows}
              density="dense"
              caption="Backend microservices and datastores health overview"
            />
          </section>
        )}

        <AuditLine actor="System Health Sentinel" time={lastCheckedTime} />
      </main>
    </div>
  );
};

export default HealthPage;
