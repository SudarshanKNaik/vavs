"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";

import { useLocalAuth } from "@/lib/local-auth";
import {
  getBloodCampaignMap,
  getBloodCampaignStatus,
  listBloodCampaignDonors,
  listBloodCampaignNgos,
  startBloodCampaign,
  uploadBloodCampaignSheet,
  type BloodCampaignAttempt,
  type BloodCampaignMapPayload,
  type BloodDonorItem,
  type BloodNgoItem,
} from "@/services/api";
import { Button } from "@/components/ui/button";

const BloodCampaignMap = dynamic(
  () => import("@/components/blood/BloodCampaignMap"),
  { ssr: false },
);

type UploadSummary = {
  donors?: { accepted: number; created: number; updated: number };
  ngos?: { accepted: number; created: number; updated: number };
  rejected_rows?: Array<{ sheet: string; row: number; error: string }>;
};

const DONOR_COLUMNS = [
  "name",
  "gender",
  "phone_number",
  "location",
  "last_donated_date",
  "blood_type",
] as const;

const NGO_COLUMNS = ["ngo_name", "phone_number", "location"] as const;
const MIXED_SHEET_OPTIONAL_COLUMNS = ["ngo_name", "row_type"] as const;

const RECIPIENT_COMPATIBLE_DONORS: Record<string, string[]> = {
  "O-": ["O-"],
  "O+": ["O+", "O-"],
  "A-": ["A-", "O-"],
  "A+": ["A+", "A-", "O+", "O-"],
  "B-": ["B-", "O-"],
  "B+": ["B+", "B-", "O+", "O-"],
  "AB-": ["AB-", "A-", "B-", "O-"],
  "AB+": ["AB+", "AB-", "A+", "A-", "B+", "B-", "O+", "O-"],
};

function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 KB";
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(2)} MB`;
}

function cooldownDaysForGender(gender: string): number {
  const normalized = (gender || "").trim().toLowerCase();
  if (normalized === "male" || normalized === "m") return 90;
  if (normalized === "female" || normalized === "f") return 120;
  return 120;
}

function isCooldownPassed(lastDonatedDate: string, gender: string): boolean {
  const donatedAt = new Date(lastDonatedDate);
  if (Number.isNaN(donatedAt.getTime())) return false;
  const msPerDay = 1000 * 60 * 60 * 24;
  const elapsed = (Date.now() - donatedAt.getTime()) / msPerDay;
  return elapsed >= cooldownDaysForGender(gender);
}

function isBloodTypeCompatible(donorBloodType: string, recipientBloodType: string): boolean {
  const donor = (donorBloodType || "").toUpperCase().trim();
  const recipient = (recipientBloodType || "").toUpperCase().trim();
  if (!donor || !recipient) return false;

  const compatibleDonors = RECIPIENT_COMPATIBLE_DONORS[recipient] || [];
  return compatibleDonors.includes(donor);
}

export default function BloodCampaignPage() {
  const { user } = useLocalAuth();
  const doctorId = user?.doctor_id || user?.sub || "";

  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadSummary, setUploadSummary] = useState<UploadSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [donors, setDonors] = useState<BloodDonorItem[]>([]);
  const [ngos, setNgos] = useState<BloodNgoItem[]>([]);
  const [loadingData, setLoadingData] = useState(false);

  const [bloodType, setBloodType] = useState("O+");
  const [recipientName, setRecipientName] = useState("");
  const [reason, setReason] = useState("");
  const [patientLocation, setPatientLocation] = useState("");
  const [batchSize, setBatchSize] = useState(3);

  const [startingCampaign, setStartingCampaign] = useState(false);
  const [campaignId, setCampaignId] = useState<string | null>(null);
  const [campaignStatus, setCampaignStatus] = useState<string | null>(null);
  const [attempts, setAttempts] = useState<BloodCampaignAttempt[]>([]);
  const [summary, setSummary] = useState({ active: 0, completed: 0, accepted: false });
  const [mapPayload, setMapPayload] = useState<BloodCampaignMapPayload | null>(null);

  const refreshUploadedData = useCallback(async () => {
    if (!doctorId) return;
    setLoadingData(true);
    setError(null);
    try {
      const [fetchedDonors, fetchedNgos] = await Promise.all([
        listBloodCampaignDonors(doctorId),
        listBloodCampaignNgos(doctorId),
      ]);
      setDonors(fetchedDonors);
      setNgos(fetchedNgos);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to load uploaded data";
      setError(message);
    } finally {
      setLoadingData(false);
    }
  }, [doctorId]);

  const refreshCampaign = useCallback(async (id: string) => {
    try {
      const [detail, map] = await Promise.all([
        getBloodCampaignStatus(id),
        getBloodCampaignMap(id),
      ]);
      setCampaignStatus(String(detail.campaign?.status || "unknown"));
      setAttempts(detail.attempts || []);
      setSummary(detail.summary || { active: 0, completed: 0, accepted: false });
      setMapPayload(map);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to load campaign status";
      setError(message);
    }
  }, []);

  useEffect(() => {
    if (!doctorId) return;
    void refreshUploadedData();
  }, [doctorId, refreshUploadedData]);

  useEffect(() => {
    if (!campaignId) return;

    const interval = window.setInterval(() => {
      void refreshCampaign(campaignId);
    }, 5000);

    return () => window.clearInterval(interval);
  }, [campaignId, refreshCampaign]);

  const bloodTypeOptions = useMemo(() => {
    const options = new Set<string>(["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]);
    donors.forEach((donor) => options.add((donor.blood_type || "").toUpperCase()));
    return Array.from(options).filter(Boolean).sort();
  }, [donors]);

  const donorPreview = useMemo(() => {
    return donors.map((donor) => {
      const bloodCompatible = isBloodTypeCompatible(donor.blood_type, bloodType);
      const cooldownPassed = isCooldownPassed(donor.last_donated_date, donor.gender);
      return {
        ...donor,
        bloodCompatible,
        cooldownPassed,
        eligible: bloodCompatible && cooldownPassed,
      };
    });
  }, [donors, bloodType]);

  const activeAttempts = attempts.filter((item) => item.status === "active" || item.status === "queued");
  const completedAttempts = attempts.filter((item) => ["completed", "accepted", "failed"].includes(item.status));

  const eligibilitySummary = useMemo(() => {
    const eligible = donorPreview.filter((item) => item.eligible).length;
    const bloodMismatch = donorPreview.filter((item) => !item.bloodCompatible).length;
    const cooldownPending = donorPreview.filter(
      (item) => item.bloodCompatible && !item.cooldownPassed,
    ).length;
    return { eligible, bloodMismatch, cooldownPending };
  }, [donorPreview]);

  const fallbackMapPayload: BloodCampaignMapPayload = useMemo(
    () => ({
      campaign_id: campaignId || "preview",
      patient: {
        location: patientLocation,
      },
      donors: donorPreview.map((item) => ({
        id: item.id,
        name: item.name,
        blood_type: item.blood_type,
        location: item.location,
        latitude: item.latitude,
        longitude: item.longitude,
        status: item.eligible ? "queued" : "not-contacted",
      })),
      ngos: ngos.map((item) => ({
        id: item.id,
        name: item.ngo_name,
        location: item.location,
        latitude: item.latitude,
        longitude: item.longitude,
      })),
    }),
    [campaignId, patientLocation, donorPreview, ngos],
  );

  const currentMap = mapPayload || fallbackMapPayload;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Blood Campaign</h1>
        <p className="text-sm text-muted-foreground">
          Upload donor/NGO Excel, review in table + map, then start eligibility-based calling.
        </p>
      </div>

      {error ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      <section className="rounded-xl border border-border bg-card p-5 space-y-4">
        <h2 className="text-sm font-semibold">1) Upload Excel</h2>
        <div className="rounded-lg border border-border bg-muted/20 p-4 space-y-3">
          <p className="text-sm text-muted-foreground">
            Upload here in this section. Only <span className="font-medium text-foreground">.xlsx</span> files are accepted, max size 10 MB.
          </p>

          <div className="flex flex-col gap-3 md:flex-row md:items-center">
            <input
              type="file"
              accept=".xlsx"
              onChange={(event) => setFile(event.target.files?.[0] || null)}
              className="text-sm"
            />
            <Button
              disabled={!file || !doctorId || uploading}
              onClick={async () => {
                if (!file || !doctorId) return;
                setUploading(true);
                setError(null);
                try {
                  const result = await uploadBloodCampaignSheet(file, doctorId);
                  setUploadSummary(result);
                  await refreshUploadedData();
                } catch (err) {
                  const message = err instanceof Error ? err.message : "Upload failed";
                  setError(message);
                } finally {
                  setUploading(false);
                }
              }}
            >
              {uploading ? "Uploading..." : "Upload & Store"}
            </Button>
            <Button variant="outline" disabled={loadingData || !doctorId} onClick={() => void refreshUploadedData()}>
              Refresh Data
            </Button>
          </div>

          {file ? (
            <div className="rounded-md border border-border bg-background p-3 text-xs text-muted-foreground">
              <p>
                Selected file: <span className="font-medium text-foreground">{file.name}</span>
              </p>
              <p>Size: {formatFileSize(file.size)}</p>
            </div>
          ) : null}
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-lg border border-border p-3 text-sm">
            <p className="font-medium mb-2">Required Sheet: Donors</p>
            <p className="text-xs text-muted-foreground mb-2">Columns (exact names):</p>
            <div className="flex flex-wrap gap-1.5">
              {DONOR_COLUMNS.map((column) => (
                <span key={column} className="rounded-full bg-muted px-2 py-0.5 text-[11px]">
                  {column}
                </span>
              ))}
            </div>
          </div>
          <div className="rounded-lg border border-border p-3 text-sm">
            <p className="font-medium mb-2">Required Sheet: NGOs</p>
            <p className="text-xs text-muted-foreground mb-2">Columns (exact names):</p>
            <div className="flex flex-wrap gap-1.5">
              {NGO_COLUMNS.map((column) => (
                <span key={column} className="rounded-full bg-muted px-2 py-0.5 text-[11px]">
                  {column}
                </span>
              ))}
            </div>
          </div>
        </div>

        <div className="rounded-lg border border-border p-3 text-sm space-y-2">
          <p className="font-medium">Single-Sheet Option (new)</p>
          <p className="text-xs text-muted-foreground">
            You can upload one mixed sheet instead of separate Donors/NGOs sheets.
          </p>
          <p className="text-xs text-muted-foreground">
            Required columns in the single sheet: {DONOR_COLUMNS.join(", ")}.
          </p>
          <p className="text-xs text-muted-foreground">
            Optional helper columns: {MIXED_SHEET_OPTIONAL_COLUMNS.join(", ")}.
          </p>
          <p className="text-xs text-muted-foreground">
            For NGO rows, keep donor-only fields empty (gender, last_donated_date, blood_type) and fill ngo_name (or name).
          </p>
        </div>

        <div className="rounded-lg border border-amber-400/40 bg-amber-400/10 p-3 text-xs text-amber-900">
          <p className="font-semibold">Format Rules</p>
          <p>gender: male/female or m/f</p>
          <p>blood_type: A+, A-, B+, B-, AB+, AB-, O+, O-</p>
          <p>last_donated_date: YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY, or YYYY/MM/DD</p>
          <p>location: lat,lng preferred; plain text also accepted and auto-geocoded when possible</p>
          <p>single sheet NGO row typing: row_type=ngo OR ngo_name present OR donor-only fields left empty</p>
        </div>

        {uploadSummary ? (
          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-lg border border-border p-3 text-sm">
              <p className="font-medium">Donors</p>
              <p>Accepted: {uploadSummary.donors?.accepted ?? 0}</p>
              <p>Created: {uploadSummary.donors?.created ?? 0}</p>
              <p>Updated: {uploadSummary.donors?.updated ?? 0}</p>
            </div>
            <div className="rounded-lg border border-border p-3 text-sm">
              <p className="font-medium">NGOs</p>
              <p>Accepted: {uploadSummary.ngos?.accepted ?? 0}</p>
              <p>Created: {uploadSummary.ngos?.created ?? 0}</p>
              <p>Updated: {uploadSummary.ngos?.updated ?? 0}</p>
            </div>
            {(uploadSummary.rejected_rows || []).length > 0 ? (
              <div className="md:col-span-2 rounded-lg border border-amber-400/40 bg-amber-400/10 p-3 text-sm">
                <p className="font-medium">Rejected Rows</p>
                <ul className="mt-1 space-y-1">
                  {uploadSummary.rejected_rows?.slice(0, 20).map((item, index) => (
                    <li key={`${item.sheet}-${item.row}-${index}`}>
                      {item.sheet} row {item.row}: {item.error}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : null}
      </section>

      <section className="rounded-xl border border-border bg-card p-5 space-y-4">
        <h2 className="text-sm font-semibold">2) Review Uploaded Data</h2>

        <div className="grid gap-3 sm:grid-cols-3 text-sm">
          <div className="rounded-lg border border-border p-3">
            <p className="text-muted-foreground">Eligible Preview</p>
            <p className="text-xl font-semibold">{eligibilitySummary.eligible}</p>
          </div>
          <div className="rounded-lg border border-border p-3">
            <p className="text-muted-foreground">Blood Type Mismatch</p>
            <p className="text-xl font-semibold">{eligibilitySummary.bloodMismatch}</p>
          </div>
          <div className="rounded-lg border border-border p-3">
            <p className="text-muted-foreground">Cooldown Pending</p>
            <p className="text-xl font-semibold">{eligibilitySummary.cooldownPending}</p>
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground mb-2">
              Donors ({donors.length})
            </p>
            <div className="max-h-72 overflow-auto rounded-lg border border-border">
              <table className="w-full text-sm">
                <thead className="bg-muted/40 sticky top-0">
                  <tr>
                    <th className="text-left px-3 py-2">Name</th>
                    <th className="text-left px-3 py-2">Phone</th>
                    <th className="text-left px-3 py-2">Blood</th>
                    <th className="text-left px-3 py-2">Cooldown</th>
                    <th className="text-left px-3 py-2">Eligible</th>
                  </tr>
                </thead>
                <tbody>
                  {donorPreview.map((donor) => (
                    <tr key={donor.id} className="border-t border-border">
                      <td className="px-3 py-2">{donor.name}</td>
                      <td className="px-3 py-2">{donor.phone_number}</td>
                      <td className="px-3 py-2">{donor.blood_type}</td>
                      <td className="px-3 py-2">{donor.cooldownPassed ? "Passed" : "Pending"}</td>
                      <td className="px-3 py-2">
                        <span className={donor.eligible ? "text-green-600" : "text-muted-foreground"}>
                          {donor.eligible ? "Yes" : "No"}
                        </span>
                      </td>
                    </tr>
                  ))}
                  {donorPreview.length === 0 ? (
                    <tr>
                      <td className="px-3 py-3 text-muted-foreground" colSpan={5}>
                        No donors uploaded yet.
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </div>

          <div>
            <p className="text-xs uppercase tracking-wide text-muted-foreground mb-2">
              NGOs ({ngos.length})
            </p>
            <div className="max-h-72 overflow-auto rounded-lg border border-border">
              <table className="w-full text-sm">
                <thead className="bg-muted/40 sticky top-0">
                  <tr>
                    <th className="text-left px-3 py-2">NGO</th>
                    <th className="text-left px-3 py-2">Phone</th>
                    <th className="text-left px-3 py-2">Location</th>
                  </tr>
                </thead>
                <tbody>
                  {ngos.map((ngo) => (
                    <tr key={ngo.id} className="border-t border-border">
                      <td className="px-3 py-2">{ngo.ngo_name}</td>
                      <td className="px-3 py-2">{ngo.phone_number}</td>
                      <td className="px-3 py-2">{ngo.location}</td>
                    </tr>
                  ))}
                  {ngos.length === 0 ? (
                    <tr>
                      <td className="px-3 py-3 text-muted-foreground" colSpan={3}>
                        No NGOs uploaded yet.
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <BloodCampaignMap
          patient={currentMap.patient}
          donors={currentMap.donors}
          ngos={currentMap.ngos}
        />
      </section>

      <section className="rounded-xl border border-border bg-card p-5 space-y-4">
        <h2 className="text-sm font-semibold">3) Start Calling Campaign</h2>

        <div className="grid gap-3 md:grid-cols-2">
          <label className="text-sm space-y-1">
            <span>Blood Type Needed</span>
            <select
              value={bloodType}
              onChange={(event) => setBloodType(event.target.value)}
              className="w-full rounded-md border border-input bg-background px-3 py-2"
            >
              {bloodTypeOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>

          <label className="text-sm space-y-1">
            <span>Recipient Name</span>
            <input
              value={recipientName}
              onChange={(event) => setRecipientName(event.target.value)}
              placeholder="e.g. Patient Name"
              className="w-full rounded-md border border-input bg-background px-3 py-2"
            />
          </label>

          <label className="text-sm space-y-1">
            <span>Recipient Location (optional)</span>
            <input
              value={patientLocation}
              onChange={(event) => setPatientLocation(event.target.value)}
              placeholder="lat,lng or address text"
              className="w-full rounded-md border border-input bg-background px-3 py-2"
            />
          </label>

          <label className="text-sm space-y-1">
            <span>Batch Size</span>
            <input
              type="number"
              min={1}
              max={10}
              value={batchSize}
              onChange={(event) => setBatchSize(Number(event.target.value || 3))}
              className="w-full rounded-md border border-input bg-background px-3 py-2"
            />
          </label>

          <label className="text-sm space-y-1 md:col-span-2">
            <span>Why Needed (optional)</span>
            <textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              rows={3}
              className="w-full rounded-md border border-input bg-background px-3 py-2"
            />
          </label>
        </div>

        <div className="flex items-center gap-3">
          <Button
            disabled={!doctorId || !recipientName.trim() || !bloodType || startingCampaign}
            onClick={async () => {
              if (!doctorId) return;
              setStartingCampaign(true);
              setError(null);
              try {
                const response = await startBloodCampaign({
                  doctor_id: doctorId,
                  blood_type: bloodType,
                  recipient_name: recipientName,
                  reason: reason || null,
                  patient_location: patientLocation || null,
                  batch_size: batchSize,
                });
                setCampaignId(response.campaign_id);
                setCampaignStatus(response.status);
                await refreshCampaign(response.campaign_id);
              } catch (err) {
                const message = err instanceof Error ? err.message : "Campaign start failed";
                setError(message);
              } finally {
                setStartingCampaign(false);
              }
            }}
          >
            {startingCampaign ? "Starting..." : "Start Campaign"}
          </Button>

          {campaignId ? (
            <p className="text-sm text-muted-foreground">
              Campaign: <span className="font-mono">{campaignId.slice(0, 8)}...</span> | Status: {campaignStatus}
            </p>
          ) : null}
        </div>
      </section>

      <section className="rounded-xl border border-border bg-card p-5 space-y-4">
        <h2 className="text-sm font-semibold">4) Live Call Status</h2>

        <div className="grid gap-3 md:grid-cols-3 text-sm">
          <div className="rounded-lg border border-border p-3">
            <p className="text-muted-foreground">Active</p>
            <p className="text-xl font-semibold">{summary.active}</p>
          </div>
          <div className="rounded-lg border border-border p-3">
            <p className="text-muted-foreground">Completed</p>
            <p className="text-xl font-semibold">{summary.completed}</p>
          </div>
          <div className="rounded-lg border border-border p-3">
            <p className="text-muted-foreground">Accepted</p>
            <p className="text-xl font-semibold">{summary.accepted ? "Yes" : "No"}</p>
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-lg border border-border p-3">
            <p className="text-xs uppercase tracking-wide text-muted-foreground mb-2">
              Active / Queued Calls
            </p>
            <ul className="space-y-2 text-sm">
              {activeAttempts.map((item) => (
                <li key={item.id} className="border border-border rounded-md p-2">
                  <p className="font-medium">{item.donor_name || item.donor_id}</p>
                  <p className="text-muted-foreground">Status: {item.status}</p>
                  <p className="text-muted-foreground">Worker: {item.worker_name || "default"}</p>
                </li>
              ))}
              {activeAttempts.length === 0 ? (
                <li className="text-muted-foreground">No active calls.</li>
              ) : null}
            </ul>
          </div>

          <div className="rounded-lg border border-border p-3">
            <p className="text-xs uppercase tracking-wide text-muted-foreground mb-2">
              Completed Calls
            </p>
            <ul className="space-y-2 text-sm max-h-64 overflow-auto">
              {completedAttempts.map((item) => (
                <li key={item.id} className="border border-border rounded-md p-2">
                  <p className="font-medium">{item.donor_name || item.donor_id}</p>
                  <p className="text-muted-foreground">Status: {item.status}</p>
                  <p className="text-muted-foreground">Outcome: {item.outcome || "-"}</p>
                </li>
              ))}
              {completedAttempts.length === 0 ? (
                <li className="text-muted-foreground">No completed calls yet.</li>
              ) : null}
            </ul>
          </div>
        </div>
      </section>
    </div>
  );
}
