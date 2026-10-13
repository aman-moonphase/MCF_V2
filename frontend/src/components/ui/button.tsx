import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  asChild?: boolean
  variant?: "default" | "outline" | "ghost" | "secondary"
  size?: "default" | "sm" | "lg" | "icon"
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button"
    
    // Base styles
    let baseStyles = "inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 cursor-pointer disabled:cursor-not-allowed"
    
    // Variant styles
    let variantStyles = ""
    if (variant === "default") variantStyles = "bg-primary text-primary-foreground hover:bg-primary/90"
    else if (variant === "outline") variantStyles = "border border-border bg-background hover:bg-muted hover:text-foreground"
    else if (variant === "ghost") variantStyles = "hover:bg-muted hover:text-foreground"
    else if (variant === "secondary") variantStyles = "bg-muted text-foreground hover:bg-muted/80"

    // Size styles
    let sizeStyles = ""
    if (size === "default") sizeStyles = "h-10 px-4 py-2"
    else if (size === "sm") sizeStyles = "h-9 rounded-md px-3"
    else if (size === "lg") sizeStyles = "h-11 rounded-md px-8"
    else if (size === "icon") sizeStyles = "h-10 w-10"

    return (
      <Comp
        className={cn(baseStyles, variantStyles, sizeStyles, className)}
        ref={ref}
        {...props}
      />
    )
  }
)
Button.displayName = "Button"

export { Button }
