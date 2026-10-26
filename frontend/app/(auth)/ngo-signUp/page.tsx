"use client";

import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useLocalAuth } from "@/lib/local-auth";
import { NgoApiError, registerNgo, sendNgoRegistrationOtp, type NgoRegisterInput } from "@/services/ngo-api";
import { Button } from "@/components/ui/button";

type FormValues = Required<NgoRegisterInput> & { confirm_password: string };
type FieldErrors = Partial<Record<keyof FormValues, string>>;

const EMPTY: FormValues = {
  ngo_name: "",
  city: "",
  darpan_id: "",
  contact_phone: "",
  admin_name: "",
  email: "",
  mobile: "",
  password: "",
  confirm_password: "",
  otp_code: "",
};

const inputClass =
  "w-full rounded-lg border border-border bg-background px-3 py-2 text-sm aria-invalid:border-destructive";

function validate(values: FormValues): FieldErrors {
  const errors: FieldErrors = {};
  if (values.ngo_name.trim().length < 3) errors.ngo_name = "NGO name must be at least 3 characters";
  if (!/^\d{5}$/.test(values.darpan_id.trim())) errors.darpan_id = "Darpan ID must be exactly 5 digits";
  if (values.admin_name.trim().length < 2) errors.admin_name = "Your name must be at least 2 characters";
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(values.email.trim())) errors.email = "Enter a valid email address";
  if (values.password.length < 8) errors.password = "Password must be at least 8 characters";
  if (values.confirm_password !== values.password) errors.confirm_password = "Passwords do not match";
  if (!/^\d{6}$/.test(values.otp_code.trim())) errors.otp_code = "Enter the 6-digit code sent to your email";
  return errors;
}

export default function NgoSignUp() {
  const { startSession, isLoading } = useLocalAuth();
  const router = useRouter();
  const [values, setValues] = useState<FormValues>(EMPTY);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [error, setError] = useState<string | null>(null);
  const [otpMessage, setOtpMessage] = useState<string | null>(null);
  const [sendingOtp, setSendingOtp] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const set = (field: keyof FormValues) => (e: React.ChangeEvent<HTMLInputElement>) => {
    setValues((v) => ({ ...v, [field]: e.target.value }));
    setErrors((prev) => ({ ...prev, [field]: undefined }));
  };

  const handleSendOtp = async () => {
    setError(null);
    setOtpMessage(null);
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(values.email.trim())) {
      setErrors((prev) => ({ ...prev, email: "Enter your email before requesting a code" }));
      return;
    }
    setSendingOtp(true);
    try {
      await sendNgoRegistrationOtp(values.email.trim());
      setOtpMessage("Verification code sent. It expires in 10 minutes.");
    } catch (err) {
      if (err instanceof NgoApiError && err.detail.field_errors) setErrors(err.detail.field_errors as FieldErrors);
      setError(err instanceof Error ? err.message : "Failed to send code");
    } finally {
      setSendingOtp(false);
    }
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting) return;
    const clientErrors = validate(values);
    setErrors(clientErrors);
    setError(null);
    if (Object.keys(clientErrors).length > 0) return;

    setSubmitting(true);
    try {
      const { confirm_password: _unused, ...payload } = values;
      void _unused;
      startSession(
        await registerNgo({
          ...payload,
          ngo_name: payload.ngo_name.trim(),
          darpan_id: payload.darpan_id.trim(),
          admin_name: payload.admin_name.trim(),
          email: payload.email.trim(),
          otp_code: payload.otp_code.trim(),
        }),
      );
      router.push("/ngo/dashboard");
    } catch (err) {
      if (err instanceof NgoApiError && err.detail.field_errors) setErrors(err.detail.field_errors as FieldErrors);
      setError(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setSubmitting(false);
    }
  };

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading...</p>;
  }

  const field = (
    name: keyof FormValues,
    label: string,
    props: React.InputHTMLAttributes<HTMLInputElement> = {},
  ) => (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-muted-foreground">{label}</span>
      <input
        value={values[name]}
        onChange={set(name)}
        aria-invalid={!!errors[name]}
        aria-describedby={errors[name] ? `${name}-error` : undefined}
        className={inputClass}
        {...props}
      />
      {errors[name] && <span id={`${name}-error`} className="mt-1 block text-xs text-destructive">{errors[name]}</span>}
    </label>
  );

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Register your NGO</h1>
        <p className="text-sm text-muted-foreground">Create your organization and its first admin account.</p>
      </div>

      <fieldset className="space-y-3">
        <legend className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Organization</legend>
        {field("ngo_name", "NGO name *", { maxLength: 200, autoComplete: "organization" })}
        <div className="grid gap-3 sm:grid-cols-2">
          {field("city", "City", { maxLength: 100, autoComplete: "address-level2" })}
          {field("darpan_id", "Darpan ID (5 digits) *", { inputMode: "numeric", pattern: "[0-9]{5}", maxLength: 5, placeholder: "12345" })}
        </div>
        {field("contact_phone", "Organization phone", { type: "tel", maxLength: 20 })}
      </fieldset>

      <fieldset className="space-y-3">
        <legend className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Admin account</legend>
        {field("admin_name", "Your name *", { maxLength: 200, autoComplete: "name" })}
        {field("mobile", "Mobile number", { type: "tel", maxLength: 20, autoComplete: "tel" })}
        {field("email", "Email *", { type: "email", maxLength: 254, autoComplete: "email" })}
        <div className="flex items-end gap-2">
          <div className="flex-1">{field("otp_code", "Email verification code *", { inputMode: "numeric", maxLength: 6, autoComplete: "one-time-code" })}</div>
          <Button type="button" variant="secondary" onClick={handleSendOtp} disabled={sendingOtp} className={errors.otp_code ? "mb-5" : undefined}>
            {sendingOtp ? "Sending..." : "Send code"}
          </Button>
        </div>
        {otpMessage && <p role="status" className="text-xs text-success">{otpMessage}</p>}
        <div className="grid gap-3 sm:grid-cols-2">
          {field("password", "Password *", { type: "password", minLength: 8, autoComplete: "new-password" })}
          {field("confirm_password", "Confirm password *", { type: "password", autoComplete: "new-password" })}
        </div>
      </fieldset>

      {error && <p role="alert" className="text-xs text-destructive">{error}</p>}

      <Button type="submit" disabled={submitting}>
        {submitting ? "Creating NGO..." : "Register NGO"}
      </Button>

      <p className="text-xs text-muted-foreground">
        Already registered? <Link href="/ngo-signIn" className="underline">NGO login</Link>
      </p>
    </form>
  );
}
