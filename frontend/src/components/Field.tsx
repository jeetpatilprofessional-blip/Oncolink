import React, { useId } from "react";

export interface FieldProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
  hint?: string;
}

/**
 * Standard ONCOLINK Form Field Component.
 * - Visible label above the field, never placeholder-only.
 * - Error message below, linked via aria-describedby and aria-invalid.
 * - White input background, 4px radius, rule border.
 */
export const Field: React.FC<FieldProps> = ({
  label,
  error,
  hint,
  id: customId,
  className = "",
  disabled = false,
  ...inputProps
}) => {
  const generatedId = useId();
  const inputId = customId || `field-${generatedId}`;
  const errorId = `${inputId}-error`;
  const hintId = `${inputId}-hint`;

  const describedBy =
    [error ? errorId : null, hint ? hintId : null].filter(Boolean).join(" ") || undefined;

  return (
    <div className={`flex flex-col gap-1 w-full text-left font-sans ${className}`.trim()}>
      <label htmlFor={inputId} className="text-sm font-medium text-[#18242C]">
        {label}
      </label>

      {hint && (
        <span id={hintId} className="text-xs text-[#18242C]/70">
          {hint}
        </span>
      )}

      <input
        id={inputId}
        disabled={disabled}
        aria-invalid={Boolean(error)}
        aria-describedby={describedBy}
        className={`w-full min-h-[44px] px-3 py-2 text-sm bg-white text-[#18242C] rounded-[4px] border ${
          error ? "border-[#B42318]" : "border-[#D5DAD8]"
        } focus-visible:outline-2 focus-visible:outline-[#4B2E83] focus-visible:outline-offset-2 disabled:bg-[#F5F7F6] disabled:text-[#18242C]/50 disabled:cursor-not-allowed transition-colors`}
        {...inputProps}
      />

      {error && (
        <span id={errorId} role="alert" className="text-xs text-[#B42318] font-medium mt-0.5">
          {error}
        </span>
      )}
    </div>
  );
};
