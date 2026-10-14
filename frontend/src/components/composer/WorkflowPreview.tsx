"use client"

import * as React from "react"
import { motion } from "framer-motion"
import { cn } from "@/lib/utils"

const WORKFLOW_STEPS = [
  { id: "source", label: "Source Grounding" },
  { id: "content", label: "Content Selection" },
  { id: "platforms", label: "Platform Strategy" },
  { id: "angle", label: "Topic & Angle" },
  { id: "strategy", label: "Content Strategy" },
  { id: "storyboard", label: "Storyboard" },
  { id: "script", label: "Final Script" },
]

export function WorkflowPreview() {
  const [activeIndex, setActiveIndex] = React.useState(0);

  React.useEffect(() => {
    const interval = setInterval(() => {
      setActiveIndex((current) => (current + 1) % WORKFLOW_STEPS.length);
    }, 2000);
    return () => clearInterval(interval);
  }, []);

  return (
    <motion.div 
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.7, delay: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className="flex flex-col w-full"
    >
      <h3 className="text-xs font-bold uppercase tracking-widest text-slate-400 dark:text-muted-foreground mb-8 text-center sm:text-left">
        Your Workflow
      </h3>
      
      <div className="relative w-full overflow-x-auto pb-6 hide-scrollbar">
        <div className="relative flex flex-row items-start justify-between min-w-[700px] w-full px-4 sm:px-2">
          {/* Subtle background horizontal track */}
          <div className="absolute left-8 right-8 top-[9px] h-[2px] bg-slate-200 dark:bg-border/60" />
          
          {WORKFLOW_STEPS.map((step, index) => {
            const isActive = index === activeIndex;
            const isCompleted = index < activeIndex;
            
            return (
              <div key={step.id} className="relative flex flex-col items-center gap-4 group w-24">
                <div className="relative z-10 flex h-5 w-5 items-center justify-center rounded-full bg-background border-[3px] border-background">
                  {isActive ? (
                    <>
                      <div className="absolute inset-0 rounded-full bg-primary/20 animate-ping" style={{ animationDuration: '3s' }} />
                      <div className="h-2.5 w-2.5 rounded-full bg-primary shadow-[0_0_12px_2px_rgba(99,102,241,0.5)]" />
                    </>
                  ) : isCompleted ? (
                    <div className="h-2 w-2 rounded-full bg-primary/40 dark:bg-primary/50 transition-colors" />
                  ) : (
                    <div className="h-1.5 w-1.5 rounded-full bg-slate-300 dark:bg-slate-700 transition-colors group-hover:bg-primary/40" />
                  )}
                </div>
                
                <span className={cn(
                  "text-[13px] leading-tight text-center tracking-tight transition-colors duration-300 px-1",
                  isActive ? "font-bold text-foreground" : 
                  isCompleted ? "font-medium text-slate-500 dark:text-slate-400" : 
                  "text-slate-400 dark:text-slate-500 group-hover:text-foreground font-medium"
                )}>
                  {step.label}
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </motion.div>
  )
}
