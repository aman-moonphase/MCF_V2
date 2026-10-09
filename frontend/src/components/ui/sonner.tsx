"use client"

import { useTheme } from "next-themes"
import { Toaster as Sonner } from "sonner"

// The single app-level toast container. Any component can call `toast(...)` from "sonner".
export function Toaster() {
  const { resolvedTheme } = useTheme()

  return (
    <Sonner
      theme={resolvedTheme === "light" ? "light" : "dark"}
      position="bottom-right"
      richColors
      closeButton
    />
  )
}
