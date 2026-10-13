import * as React from "react"
import { cn } from "@/lib/utils"

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "secondary" | "destructive" | "outline"
}

function Badge({ className, variant = "default", ...props }: BadgeProps) {
  let variantStyles = ""
  if (variant === "default") variantStyles = "border-transparent bg-primary text-primary-foreground hover:bg-primary/80"
  else if (variant === "secondary") variantStyles = "border-transparent bg-muted text-foreground hover:bg-muted/80"
  else if (variant === "destructive") variantStyles = "border-transparent bg-red-500 text-white hover:bg-red-500/80"
  else if (variant === "outline") variantStyles = "text-foreground"

  return (
    <div
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
        props.onClick && "cursor-pointer",
        variantStyles,
        className
      )}
      {...props}
    />
  )
}

export { Badge }
