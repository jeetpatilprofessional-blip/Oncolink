import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createCase, listCases } from "../api/client";
import type { CaseStatusResponse } from "../api/types";
import { Banner } from "../components/Banner";
import { Button } from "../components/Button";
import { type Column, DataTable } from "../components/DataTable";
import { Nav } from "../components/Nav";
import { StatusMarker } from "../components/StatusMarker";
import { t } from "../locales/i18n";

export const PatientHomePage: React.FC = () => {
  const navigate = useNavigate();
  const [cases, setCases] = useState<CaseStatusResponse[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [creatingCase, setCreatingCase] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;
    listCases()
      .then((data) => {
        if (isMounted) setCases(data);
      })
      .catch((err) => {
        if (isMounted) setErrorMsg(err.message || t("errors.generic_error"));
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, []);

  const handleStartScreening = async () => {
    setCreatingCase(true);
    setErrorMsg(null);
    try {
      const newCase = await createCase();
      navigate(`/cases/${newCase.id}/capture`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t("errors.generic_error");
      setErrorMsg(msg);
      setCreatingCase(false);
    }
  };

  const columns: Column<CaseStatusResponse>[] = [
    {
      key: "reference",
      header: "Case Reference",
      sortable: true,
      render: (row) => (
        <span className="font-bold tabular-nums text-ink hover:text-gentian">
          {row.reference}
        </span>
      ),
    },
    {
      key: "created_at",
      header: "Date Created",
      sortable: true,
      render: (row) => (
        <span className="tabular-nums text-ink/80 text-xs">
          {new Date(row.created_at).toLocaleDateString(undefined, {
            year: "numeric",
            month: "short",
            day: "numeric",
          })}
        </span>
      ),
    },
    {
      key: "status",
      header: "Status",
      sortable: true,
      render: (row) => (
        <span className="inline-block text-xs uppercase font-medium tracking-wider px-2 py-0.5 rounded-xs bg-paper border border-rule">
          {row.status.replace(/_/g, " ")}
        </span>
      ),
    },
    {
      key: "urgency",
      header: "Urgency",
      sortable: true,
      render: (row) => {
        if (!row.urgency) {
          return <span className="text-ink/40 text-xs">—</span>;
        }
        return <StatusMarker urgency={row.urgency} />;
      },
    },
  ];

  return (
    <div className="min-h-screen bg-paper font-sans text-ink flex flex-col">
      <Nav />
      <main className="max-w-7xl mx-auto w-full px-4 sm:px-6 lg:px-8 py-8 space-y-6">
        <Banner />

        <div className="border-b border-rule pb-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h1 className="font-serif text-2xl font-bold tracking-tight text-ink">
              {t("home.patient_title")}
            </h1>
            <p className="text-xs text-ink/70 mt-0.5">
              Access your personal oral cavity photographic records and screening status.
            </p>
          </div>
          <Button
            type="button"
            variant="primary"
            onClick={handleStartScreening}
            disabled={creatingCase}
            className="self-start sm:self-auto"
          >
            {creatingCase ? "Starting..." : t("patient_flow.start_screening")}
          </Button>
        </div>

        {errorMsg && (
          <div role="alert" className="p-3 bg-urgent/10 border-l-4 border-urgent text-xs text-ink">
            {errorMsg}
          </div>
        )}

        <div className="space-y-3">
          <h2 className="font-serif text-lg font-bold text-ink">
            {t("patient_flow.past_screenings_title")}
          </h2>

          {loading ? (
            <div className="space-y-2">
              <div className="h-10 bg-rule/30 animate-pulse rounded-none" />
              <div className="h-20 bg-rule/20 animate-pulse rounded-none" />
            </div>
          ) : cases.length === 0 ? (
            <div className="bg-white p-6 border border-rule text-center space-y-3">
              <p className="text-xs text-ink/80">{t("patient_flow.no_screenings")}</p>
              <Button type="button" variant="primary" size="sm" onClick={handleStartScreening}>
                {t("patient_flow.start_screening")}
              </Button>
            </div>
          ) : (
            <DataTable
              data={cases}
              columns={columns}
              onRowClick={(row) => {
                if (row.status === "draft" || row.status === "needs_retake") {
                  navigate(`/cases/${row.id}/capture`);
                } else {
                  navigate(`/cases/${row.id}/review`);
                }
              }}
            />
          )}
        </div>
      </main>
    </div>
  );
};
