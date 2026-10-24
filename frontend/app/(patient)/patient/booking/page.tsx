import { Suspense } from "react";
import { Loader2 } from "lucide-react";
import BookingClient from "./BookingClient";

function BookingFallback() {
  return (
    <div className="mx-auto flex min-h-screen max-w-5xl items-center justify-center px-6">
      <div className="inline-flex items-center gap-2 text-sm text-[#6E6057]">
        <Loader2 className="size-4 animate-spin" />
        Loading booking flow...
      </div>
    </div>
  );
}

export default function PatientBookingPage() {
  return (
    <Suspense fallback={<BookingFallback />}>
      <BookingClient />
    </Suspense>
  );
}
