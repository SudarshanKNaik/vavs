"use client";

import { useCallback } from "react";
import { useRouter } from "next/navigation";
import { NgoPatientForm } from "@/components/ngo/ngo-patient-form";
import { useNgoSession } from "@/components/ngo/use-ngo-session";
import { PageHeader } from "@/components/ngo/ui";
import { createNgoPatient } from "@/services/ngo-api";
import type { NgoPatientInput } from "@/types/ngo";

export default function NewNgoPatientPage() {
  const router = useRouter();
  const { token, handleError } = useNgoSession();

  const submit = useCallback(
    (payload: NgoPatientInput, key: string) => createNgoPatient(token, payload, key),
    [token],
  );

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <PageHeader
        title="Register patient"
        description="The patient is added to CareSync and assigned to the selected doctor. No calls or messages are sent automatically."
      />
      <NgoPatientForm
        onSubmit={submit}
        onError={handleError}
        onSuccess={(result) => router.push(`/ngo/patients/${result.patient_id}?registered=1`)}
      />
    </div>
  );
}
