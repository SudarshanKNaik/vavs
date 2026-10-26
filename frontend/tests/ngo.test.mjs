// Run with: npm run test:ngo  (Node >= 22.18 strips TypeScript types natively)
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  checkCsvFile,
  ngoAccessDecision,
  normalizeIndianPhone,
  validateNgoPatient,
} from "../lib/ngo-validation.ts";
import { toNgoErrorDetail } from "../services/ngo-api.ts";

const valid = {
  name: "Lakshmi Patil",
  phone: "+91 98765 43210",
  dob: "1980-08-15",
  mrn: "",
  insurance: "",
  notes: "",
  doctor_id: "1b2c3d4e-0000-0000-0000-000000000000",
};

test("valid patient has no errors", () => {
  assert.deepEqual(validateNgoPatient(valid), {});
});

test("required and malformed fields produce field-specific errors", () => {
  const errors = validateNgoPatient({ ...valid, name: " ", phone: "12345", dob: "2999-01-01", doctor_id: "" });
  assert.deepEqual(Object.keys(errors).sort(), ["dob", "doctor_id", "name", "phone"]);
  assert.match(validateNgoPatient({ ...valid, name: "=HYPERLINK()" }).name, /start with a letter/);
  assert.ok(validateNgoPatient({ ...valid, notes: "x".repeat(1001) }).notes);
});

test("phone normalization matches the backend", () => {
  assert.equal(normalizeIndianPhone("9876543210"), "+919876543210");
  assert.equal(normalizeIndianPhone("09876543210"), "+919876543210");
  assert.equal(normalizeIndianPhone("+91-98765-43210"), "+919876543210");
  assert.equal(normalizeIndianPhone("98765432101234"), null);
  assert.equal(normalizeIndianPhone("12345"), null);
});

test("route guard only allows authenticated NGO users", () => {
  assert.equal(ngoAccessDecision(true, undefined, false), "loading");
  assert.equal(ngoAccessDecision(false, undefined, false), "signin");
  assert.equal(ngoAccessDecision(false, "ngo", false), "signin");
  assert.equal(ngoAccessDecision(false, "doctor", true), "forbidden");
  assert.equal(ngoAccessDecision(false, "patient", true), "forbidden");
  assert.equal(ngoAccessDecision(false, "ngo", true), "allow");
});

test("CSV file pre-checks", () => {
  assert.equal(checkCsvFile({ name: "p.csv", size: 10 }), null);
  assert.match(checkCsvFile({ name: "p.xlsx", size: 10 }), /\.csv/);
  assert.match(checkCsvFile({ name: "p.csv", size: 0 }), /empty/);
  assert.match(checkCsvFile({ name: "p.csv", size: 3 * 1024 * 1024 }), /limit/);
});

test("API error parsing handles NGO, FastAPI validation and auth errors", () => {
  const ngo = toNgoErrorDetail(422, {
    detail: { code: "validation_error", message: "Fix fields", field_errors: { phone: "bad" } },
  });
  assert.equal(ngo.field_errors.phone, "bad");

  const pydantic = toNgoErrorDetail(422, {
    detail: [{ loc: ["body", "doctor_id"], msg: "Field required" }],
  });
  assert.deepEqual(pydantic.field_errors, { doctor_id: "Field required" });

  assert.equal(toNgoErrorDetail(401, null).code, "unauthorized");
  assert.equal(toNgoErrorDetail(409, { detail: { code: "possible_duplicate", message: "m", requires_confirmation: true } }).requires_confirmation, true);
});
