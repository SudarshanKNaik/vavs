import { useState } from "react";
import { Button } from "@/components/ui/button";
import { submitDoctorFeedback } from "@/services/api";

export interface FeedbackFormProps {
  doctorId: string;
  patientId?: string;
  onSubmitted?: () => void;
}

export default function FeedbackForm({ doctorId, patientId, onSubmitted }: FeedbackFormProps) {
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    setSuccess(false);
    try {
      await submitDoctorFeedback(doctorId, {
        rating,
        comment,
        patient_id: patientId,
      });
      setSuccess(true);
      setComment("");
      setRating(0);
      if (onSubmitted) onSubmitted();
    } catch (err: any) {
      setError(err.message || "Failed to submit feedback");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div>
        <label className="mb-1 block text-xs font-medium text-[#5E5149]">Rating</label>
        <div className="flex gap-1">
          {[1, 2, 3, 4, 5].map((star) => (
            <button
              key={star}
              type="button"
              className={
                "text-2xl transition-colors " + (star <= rating ? "text-amber-500" : "text-stone-300 hover:text-stone-400")
              }
              onClick={() => setRating(star)}
              aria-label={`Rate ${star} star${star > 1 ? "s" : ""}`}
            >
              ★
            </button>
          ))}
        </div>
      </div>
      <div>
        <label className="mb-1 block text-xs font-medium text-[#5E5149]">Feedback</label>
        <textarea
          className="w-full rounded-lg border border-border/80 bg-background px-3 py-2 text-sm placeholder:text-[#8C7B70] focus:border-primary/30 focus:outline-none focus:ring-2 focus:ring-primary/20"
          rows={3}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="Write your feedback..."
        />
      </div>
      {error && <div className="text-xs text-destructive">{error}</div>}
      {success && <div className="text-xs text-emerald-700">Thank you for your feedback!</div>}
      <Button type="submit" disabled={submitting || rating === 0}>
        {submitting ? "Submitting..." : "Submit Feedback"}
      </Button>
    </form>
  );
}
