import React, { useEffect, useState } from "react";
import {
  createStaffUser,
  deactivateUser,
  getAdminUsers,
  verifyDoctor,
} from "../api/client";
import type { AdminUser, CreateStaffPayload, DoctorVerificationStatus } from "../api/types";
import { Button } from "../components/Button";
import { type Column, DataTable } from "../components/DataTable";
import { Field } from "../components/Field";
import { Nav } from "../components/Nav";
import { useAuth } from "../context";
import { t } from "../locales/i18n";

export const AdminPage: React.FC = () => {
  const { user: currentUser } = useAuth();

  const [users, setUsers] = useState<AdminUser[]>([]);
  const [isLoadingUsers, setIsLoadingUsers] = useState(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Create staff user form state
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState<"screener" | "doctor" | "hospital_coordinator" | "admin">("doctor");
  const [newRegNumber, setNewRegNumber] = useState("");
  const [isCreating, setIsCreating] = useState(false);

  // Deactivation confirmation dialog state
  const [userToDeactivate, setUserToDeactivate] = useState<AdminUser | null>(null);
  const [isDeactivating, setIsDeactivating] = useState(false);

  const fetchUsers = async () => {
    try {
      const data = await getAdminUsers();
      setUsers(data);
    } catch (err) {
      if (import.meta.env.DEV && users.length === 0) {
        setUsers([
          {
            id: "u-1",
            email: "dr.sharma@hospital.org",
            role: "doctor",
            is_active: true,
            is_demo: false,
            created_at: "2026-10-25T10:00:00Z",
            registration_number: "MCI-45892",
            verification_status: "pending",
            totp_enrolled: true,
          },
          {
            id: "u-2",
            email: "anita.patel@example.org",
            role: "patient",
            is_active: true,
            is_demo: true,
            created_at: "2026-10-25T10:05:00Z",
            totp_enrolled: false,
          },
          {
            id: "u-3",
            email: "screener.raj@clinic.org",
            role: "screener",
            is_active: true,
            is_demo: false,
            created_at: "2026-10-25T10:10:00Z",
            totp_enrolled: true,
          },
          {
            id: "u-4",
            email: "coord.verma@district-hospital.org",
            role: "hospital_coordinator",
            is_active: true,
            is_demo: false,
            created_at: "2026-10-25T10:15:00Z",
            totp_enrolled: true,
          },
        ]);
      } else {
        setErrorMsg(err instanceof Error ? err.message : t("errors.generic_error"));
      }
    } finally {
      setIsLoadingUsers(false);
    }
  };

  useEffect(() => {
    void fetchUsers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleCreateStaff = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);
    setSuccessMsg(null);

    if (!newEmail.trim() || !newPassword) {
      setErrorMsg(t("errors.field_required"));
      return;
    }

    if (newPassword.length < 10) {
      setErrorMsg(t("errors.password_too_short"));
      return;
    }

    if (newPassword.toLowerCase() === newEmail.trim().toLowerCase()) {
      setErrorMsg(t("errors.password_equals_email"));
      return;
    }

    if (newRole === "doctor" && !newRegNumber.trim()) {
      setErrorMsg(t("errors.registration_number_required"));
      return;
    }

    setIsCreating(true);
    try {
      const payload: CreateStaffPayload = {
        email: newEmail.trim(),
        password: newPassword,
        role: newRole,
        registration_number: newRole === "doctor" ? newRegNumber.trim() : undefined,
      };
      await createStaffUser(payload);
      setSuccessMsg(t("admin.user_created_success"));
      setNewEmail("");
      setNewPassword("");
      setNewRegNumber("");
      await fetchUsers();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : t("errors.generic_error"));
    } finally {
      setIsCreating(false);
    }
  };

  const handleVerifyDoctor = async (user: AdminUser, status: DoctorVerificationStatus) => {
    setErrorMsg(null);
    setSuccessMsg(null);
    try {
      await verifyDoctor(user.id, status);
      setSuccessMsg(
        status === "verified"
          ? t("admin.doctor_verified_success")
          : t("admin.doctor_rejected_success")
      );
      await fetchUsers();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : t("errors.generic_error"));
    }
  };

  const handleConfirmDeactivate = async () => {
    if (!userToDeactivate) return;
    setErrorMsg(null);
    setSuccessMsg(null);
    setIsDeactivating(true);

    try {
      await deactivateUser(userToDeactivate.id);
      setSuccessMsg(t("admin.user_deactivated_success"));
      setUserToDeactivate(null);
      await fetchUsers();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : t("errors.generic_error"));
    } finally {
      setIsDeactivating(false);
    }
  };

  const columns: Column<AdminUser>[] = [
    {
      key: "email",
      header: "User / Identity",
      sortable: true,
      render: (row) => (
        <div className="flex flex-col py-1">
          <div className="flex items-center gap-2">
            <span className="font-medium text-ink">{row.email}</span>
            {row.is_demo && (
              <span className="text-[10px] font-bold text-amber-800 bg-amber-50 px-1 py-0.2 rounded-xs border border-amber-300">
                {t("admin.demo")}
              </span>
            )}
          </div>
          {row.registration_number && (
            <span className="text-xs font-mono text-ink/70">
              {t("admin.doctor_registration", { reg: row.registration_number })}
            </span>
          )}
        </div>
      ),
    },
    {
      key: "role",
      header: "Role",
      sortable: true,
      render: (row) => (
        <span className="text-xs font-medium uppercase tracking-wider text-ink/80 bg-paper px-2 py-0.5 rounded-xs border border-rule">
          {row.role.replace("_", " ")}
        </span>
      ),
    },
    {
      key: "is_active",
      header: "Status",
      sortable: true,
      render: (row) => (
        <span
          className={`text-xs font-semibold ${
            row.is_active ? "text-routine" : "text-ink/50 line-through"
          }`}
        >
          {row.is_active ? t("admin.active") : t("admin.inactive")}
        </span>
      ),
    },
    {
      key: "verification_status",
      header: "Doctor Verification",
      sortable: true,
      render: (row) => {
        if (row.role !== "doctor") return <span className="text-ink/40">—</span>;
        const status = row.verification_status || "pending";
        const color =
          status === "verified"
            ? "text-routine font-semibold"
            : status === "rejected"
              ? "text-urgent font-semibold"
              : "text-uncertain font-semibold";
        return <span className={`text-xs ${color}`}>{t(`admin.${status}`)}</span>;
      },
    },
    {
      key: "totp_enrolled",
      header: "2FA",
      render: (row) => (
        <span className="text-xs text-ink/80">
          {row.totp_enrolled ? "Enrolled" : "Not Enrolled"}
        </span>
      ),
    },
    {
      key: "actions",
      header: "Actions",
      align: "right",
      render: (row) => {
        const isSelf = row.id === currentUser?.id;
        return (
          <div className="flex items-center justify-end gap-2 py-0.5">
            {row.role === "doctor" && row.verification_status !== "verified" && (
              <Button
                variant="primary"
                size="sm"
                onClick={() => handleVerifyDoctor(row, "verified")}
                aria-label={`Verify doctor ${row.email}`}
              >
                {t("admin.verify_doctor")}
              </Button>
            )}
            {row.role === "doctor" && row.verification_status !== "rejected" && (
              <Button
                variant="destructive"
                size="sm"
                onClick={() => handleVerifyDoctor(row, "rejected")}
                aria-label={`Reject doctor ${row.email}`}
              >
                {t("admin.reject_doctor")}
              </Button>
            )}
            {row.is_active && !isSelf && (
              <Button
                variant="destructive"
                size="sm"
                onClick={() => setUserToDeactivate(row)}
                aria-label={`Deactivate user ${row.email}`}
              >
                {t("admin.deactivate_user")}
              </Button>
            )}
          </div>
        );
      },
    },
  ];

  return (
    <div className="min-h-screen bg-paper font-sans text-ink flex flex-col">
      <Nav />

      <main className="max-w-7xl mx-auto w-full px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        <div className="border-b border-rule pb-4">
          <h1 className="font-serif text-2xl font-bold tracking-tight text-ink">
            {t("admin.title")}
          </h1>
          <p className="mt-1 text-sm text-ink/70">
            {t("admin.subtitle")}
          </p>
        </div>

        {errorMsg && (
          <div
            role="alert"
            className="p-4 bg-urgent/10 border-l-4 border-urgent text-sm text-ink"
          >
            {errorMsg}
          </div>
        )}

        {successMsg && (
          <div
            role="status"
            className="p-4 bg-routine/10 border-l-4 border-routine text-sm text-ink"
          >
            {successMsg}
          </div>
        )}

        {/* Create Staff Form */}
        <section aria-labelledby="create-staff-heading" className="bg-white p-6 border border-rule rounded-sm shadow-xs">
          <h2 id="create-staff-heading" className="font-serif font-bold text-lg text-ink mb-4">
            {t("admin.create_user_title")}
          </h2>

          <form onSubmit={handleCreateStaff} className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 items-end">
            <Field
              id="staff-email"
              label={t("auth.email_label")}
              type="email"
              required
              autoComplete="off"
              value={newEmail}
              onChange={(e) => setNewEmail(e.target.value)}
            />

            <Field
              id="staff-password"
              label={t("auth.password_label")}
              type="password"
              required
              autoComplete="new-password"
              hint={t("errors.password_too_short")}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
            />

            <div>
              <label htmlFor="staff-role" className="block text-sm font-medium text-ink mb-1">
                {t("admin.role_select_label")}
              </label>
              <select
                id="staff-role"
                value={newRole}
                onChange={(e) =>
                  setNewRole(
                    e.target.value as "screener" | "doctor" | "hospital_coordinator" | "admin"
                  )
                }
                className="w-full h-9 px-3 bg-white border border-rule rounded-xs text-sm text-ink focus-visible:outline-2 focus-visible:outline-gentian focus-visible:outline-offset-2"
              >
                <option value="doctor">Doctor</option>
                <option value="screener">Screener</option>
                <option value="hospital_coordinator">Hospital Coordinator</option>
                <option value="admin">Administrator</option>
              </select>
            </div>

            {newRole === "doctor" ? (
              <Field
                id="staff-reg-number"
                label={t("admin.registration_number_label")}
                type="text"
                required
                placeholder="SDC-12345"
                hint={t("admin.registration_number_hint")}
                value={newRegNumber}
                onChange={(e) => setNewRegNumber(e.target.value)}
              />
            ) : (
              <div />
            )}

            <div className="md:col-span-2 lg:col-span-4 flex justify-end pt-2">
              <Button
                type="submit"
                variant="primary"
                disabled={isCreating}
              >
                {isCreating ? "Creating..." : t("admin.create_user_button")}
              </Button>
            </div>
          </form>
        </section>

        {/* Users Table */}
        <section aria-labelledby="users-table-heading" className="space-y-4">
          <h2 id="users-table-heading" className="font-serif font-bold text-lg text-ink">
            {t("admin.users_table_title")}
          </h2>

          {isLoadingUsers ? (
            <div className="p-8 text-center text-sm text-ink/70 bg-white border border-rule">
              Loading system accounts...
            </div>
          ) : (
            <DataTable<AdminUser & Record<string, unknown>>
              columns={columns as Column<AdminUser & Record<string, unknown>>[]}
              data={users as (AdminUser & Record<string, unknown>)[]}
              density="dense"
              caption="System users"
              initialSortKey="email"
              initialSortDirection="asc"
            />
          )}
        </section>

        {/* Deactivation Confirmation Modal */}
        {userToDeactivate && (
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="deactivate-modal-title"
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          >
            <div className="bg-white max-w-md w-full p-6 border border-rule rounded-sm shadow-md space-y-4">
              <h3 id="deactivate-modal-title" className="font-serif font-bold text-lg text-ink">
                {t("admin.confirm_deactivate_title")}
              </h3>
              <p className="text-sm text-ink/80 leading-relaxed">
                {t("admin.confirm_deactivate_message", { email: userToDeactivate.email })}
              </p>
              <div className="flex justify-end gap-3 pt-2">
                <Button
                  variant="secondary"
                  disabled={isDeactivating}
                  onClick={() => setUserToDeactivate(null)}
                >
                  {t("admin.cancel")}
                </Button>
                <Button
                  variant="destructive"
                  disabled={isDeactivating}
                  onClick={handleConfirmDeactivate}
                >
                  {isDeactivating ? "Deactivating..." : t("admin.confirm_deactivate_button")}
                </Button>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
};
