import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listCases } from "../api/client";
import type { CaseStatusResponse } from "../api/types";
import { Banner } from "../components/Banner";
import { Button } from "../components/Button";
import { type Column, DataTable } from "../components/DataTable";
import { Nav } from "../components/Nav";
import { t } from "../locales/i18n";

export const ScreenerHomePage: React.FC = () => {
  const navigate = useNavigate();
  const [cases, setCases] = useState<CaseStatusResponse[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
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
      header: "Time / Date",
      sortable: true,
      render: (row) => (
        <span className="tabular-nums text-ink/80 text-xs">
          {new Date(row.created_at).toLocaleString(undefined, {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
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
  ];

  return (
    <div className="min-h-screen bg-paper font-sans text-ink flex flex-col">
      <Nav />
      <main className="max-w-7xl mx-auto w-full px-4 sm:px-6 lg:px-8 py-8 space-y-6">
        <Banner />

        <div className="border-b border-rule pb-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <h1 className="font-serif text-2xl font-bold tracking-tight text-ink">
              {t("home.screener_title")}
            </h1>
            <p className="text-xs text-ink/70 mt-0.5">
              Community screening camp triage, participant intake, and photographic capture.
            </p>
          </div>
          <Button
            type="button"
            variant="primary"
            onClick={() => navigate("/screener/new-person")}
            className="self-start sm:self-auto"
          >
            {t("screener_flow.screen_new_person")}
          </Button>
        </div>

        {errorMsg && (
          <div role="alert" className="p-3 bg-urgent/10 border-l-4 border-urgent text-xs text-ink">
            {errorMsg}
          </div>
        )}

        {/* Session Ledger Table */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="font-serif text-lg font-bold text-ink">
              {t("screener_flow.session_ledger_title")}
            </h2>
            <span className="text-xs text-ink/70 tabular-nums">
              Total Screenings: <strong>{cases.length}</strong>
            </span>
          </div>

          {loading ? (
            <div className="space-y-2">
              <div className="h-10 bg-rule/30 animate-pulse rounded-none" />
              <div className="h-20 bg-rule/20 animate-pulse rounded-none" />
            </div>
          ) : cases.length === 0 ? (
            <div className="bg-white p-6 border border-rule text-center space-y-3">
              <p className="text-xs text-ink/80">{t("screener_flow.no_screenings_today")}</p>
              <Button
                type="button"
                variant="primary"
                size="sm"
                onClick={() => navigate("/screener/new-person")}
              >
                {t("screener_flow.screen_new_person")}
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
