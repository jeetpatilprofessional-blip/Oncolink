import React from "react";

export type ButtonVariant = "primary" | "secondary" | "destructive";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  children: React.ReactNode;
}

/**
 * Standard ONCOLINK Button Component.
 * - Primary: gentian fill
 * - Secondary: ink outline
 * - Destructive: ink outline (never a red fill per DESIGN.md section 8)
 * - 44px minimum touch target, 4px corner radius, no arrows in labels.
 */
export const Button: React.FC<ButtonProps> = ({
  variant = "primary",
  children,
  className = "",
  disabled = false,
  type = "button",
  ...props
}) => {
  const baseStyles =
    "inline-flex items-center justify-center px-4 py-2 min-h-[44px] rounded-[4px] font-sans text-sm font-medium transition-colors cursor-pointer select-none focus-visible:outline-2 focus-visible:outline-[#4B2E83] focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50";

  let variantStyles = "";
  if (variant === "primary") {
    variantStyles = "bg-[#4B2E83] text-white hover:bg-[#3d246c] active:bg-[#341e5c]";
  } else if (variant === "secondary") {
    variantStyles =
      "border border-[#18242C] bg-transparent text-[#18242C] hover:bg-[#18242C]/5 active:bg-[#18242C]/10";
  } else if (variant === "destructive") {
    // Destructive actions MUST use an outline, never a red fill (DESIGN.md section 8)
    variantStyles =
      "border border-[#18242C] bg-transparent text-[#18242C] hover:bg-[#18242C]/5 active:bg-[#18242C]/10";
  }

  return (
    <button
      type={type}
      disabled={disabled}
      className={`${baseStyles} ${variantStyles} ${className}`.trim()}
      {...props}
    >
      {children}
    </button>
  );
};
