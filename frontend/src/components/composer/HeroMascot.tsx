"use client"

import * as React from "react"
import { AnimatePresence, motion, useAnimationControls, useReducedMotion } from "framer-motion"
import { Heart } from "lucide-react"

// The MCF buddy. Each visit: his hands reach over the composer card's top edge, he pulls himself up (arms swing down
// to his sides), then raises an arm and waves "hi" while his eyes follow the cursor; later he sinks back down and
// repeats. Hovering keeps him up; a click makes him hop and send hearts.
//
// Artwork (public/mascot): body.png + arm-l.png + arm-r.png are layers of one cut-out character (all 364 × 412, so
// they stack exactly); the eyes are drawn on top in SVG so they can move. Transparent background, so it looks the
// same in light and dark themes. The arms are separate layers that swing about the shoulders; their inner edge fades
// into the body so there is no visible seam.
//
// He stands BEHIND the composer card (z-0 here, the card is opaque), so the card's glowing top border stays intact,
// and the floor clip below keeps any part of him from showing beneath the card.
//
// Size: the parent sets the WIDTH (e.g. "w-[96px] md:w-[124px]"); the visible height follows the aspect ratio below.

const GREETINGS = ["Hi!", "Hello!", "Hey there!", "Let's create!"]
const HIDDEN_MS = 2600   // out of sight between visits
const VISIBLE_MS = 6800  // up (grab + pull ≈ 1.7s, then waving)
const FIRST_VISIT_MS = 1400
const GRAB_MS = 450      // hands reach the edge
const PULL_MS = 1700     // pull-up finished: the wave begins
const EYE_TRAVEL = 5     // artwork units the pupils may move toward the cursor

const IMG_W = 364
const IMG_H = 412
const SHOWN = 0.7        // the top 70% of him (head, arms, chest) is above the card's edge when standing

// Shoulder pivots (% of the artwork) the arms rotate about
const L_PIVOT = "21.4% 49.4%"
const R_PIVOT = "78.4% 49.4%"

type HeartBurst = { id: number; x: number }

export function HeroMascot({ className = "" }: { className?: string }) {
  const reduceMotion = useReducedMotion()
  const [engaged, setEngaged] = React.useState(false)
  const [visiting, setVisiting] = React.useState(false)
  const [visits, setVisits] = React.useState(0)
  const [greeting, setGreeting] = React.useState(0)
  const [stage, setStage] = React.useState(0) // 0 hands on the edge · 1 pulling up · 2 up and waving
  const [hearts, setHearts] = React.useState<HeartBurst[]>([])
  const buddyRef = React.useRef<HTMLDivElement>(null)
  const hop = useAnimationControls()
  const heartId = React.useRef(0)

  const up = Boolean(reduceMotion) || engaged || visiting

  // Visiting loop: hidden → up → hidden … Hovering keeps him up; the loop carries on afterwards.
  React.useEffect(() => {
    if (reduceMotion || engaged) return
    const timer = visiting
      ? setTimeout(() => setVisiting(false), VISIBLE_MS)
      : setTimeout(() => {
          setGreeting((g) => (g + 1) % GREETINGS.length)
          setVisits((n) => n + 1)
          setVisiting(true)
        }, visits === 0 ? FIRST_VISIT_MS : HIDDEN_MS)
    return () => clearTimeout(timer)
  }, [visiting, engaged, reduceMotion, visits])

  // Stage within a visit: grab the edge → pull up → wave. Reset once he is back out of sight.
  React.useEffect(() => {
    const timers = up
      ? [setTimeout(() => setStage(1), GRAB_MS), setTimeout(() => setStage(2), PULL_MS)]
      : [setTimeout(() => setStage(0), 700)]
    return () => timers.forEach(clearTimeout)
  }, [up])

  // Eyes follow the pointer (only while he is up). Updates CSS variables, so nothing re-renders.
  React.useEffect(() => {
    if (!up || reduceMotion) return
    let frame = 0
    const onMove = (event: PointerEvent) => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        const el = buddyRef.current
        if (!el) return
        const box = el.getBoundingClientRect()
        const dx = event.clientX - (box.left + box.width / 2)
        const dy = event.clientY - (box.top + box.height * 0.23)
        const distance = Math.hypot(dx, dy) || 1
        const strength = Math.min(1, distance / 140)
        el.style.setProperty("--eye-x", `${((dx / distance) * EYE_TRAVEL * strength).toFixed(2)}px`)
        el.style.setProperty("--eye-y", `${((dy / distance) * EYE_TRAVEL * strength).toFixed(2)}px`)
      })
    }
    window.addEventListener("pointermove", onMove)
    return () => {
      window.removeEventListener("pointermove", onMove)
      cancelAnimationFrame(frame)
    }
  }, [up, reduceMotion])

  const cheer = () => {
    setVisiting(true)
    setGreeting((g) => (g + 1) % GREETINGS.length)
    if (!reduceMotion) {
      void hop.start({ y: [0, -14, 0, -6, 0], scaleY: [1, 1.06, 0.95, 1.02, 1], transition: { duration: 0.7, ease: "easeOut" } })
    }
    const burst = [0, 1, 2].map((i) => ({ id: ++heartId.current, x: 14 + i * 16 + (Math.random() * 6 - 3) }))
    setHearts((current) => [...current, ...burst])
    setTimeout(() => setHearts((current) => current.filter((h) => !burst.some((b) => b.id === h.id))), 1400)
  }

  // Poses. The artwork has both arms raised (rotate 0). Hands start out over the card's edge while his body is still
  // low behind it, the arms stay visible and lift to the cheering pose while he pulls up, then the right one waves.
  const waving = !reduceMotion && up && stage === 2
  const bodyY = reduceMotion ? "0%" : !up ? "108%" : stage === 0 ? "38%" : "0%"
  const bodyTransition = !up
    ? { duration: 0.5, ease: [0.5, 0, 0.75, 0] as const }
    : stage === 0
      ? { duration: GRAB_MS / 1000, ease: "easeOut" as const }
      : { type: "spring" as const, stiffness: 90, damping: 13, mass: 1 }
  const armsUp = !reduceMotion && (!up || stage === 0)
  const armPose = (side: 1 | -1) =>
    reduceMotion ? { rotate: 0, opacity: 1 }
    : armsUp ? { rotate: 28 * side, opacity: 1 }
    : stage === 1 ? { rotate: 0, opacity: 1 }
    : waving ? { rotate: side === 1 ? [-6, 16, -6] : [4, -8, 4], opacity: 1 }
    : { rotate: 0, opacity: 1 }
  const leftArm = armPose(-1)
  const rightArm = armPose(1)
  const armTransition = waving
    ? { rotate: { duration: 0.7, ease: "easeInOut" as const, repeat: Infinity } }
    : { type: "spring" as const, stiffness: 110, damping: 11 }

  return (
    <motion.div
      // Fades in after the composer card has finished its own entrance (it is see-through until then)
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ delay: 1.2, duration: 0.3 }}
      className={`pointer-events-auto ${className}`}
      style={{ aspectRatio: `${IMG_W} / ${IMG_H * SHOWN}` }}
      onPointerEnter={() => { setEngaged(true); setVisiting(true) }}
      onPointerLeave={() => setEngaged(false)}
      onFocus={() => { setEngaged(true); setVisiting(true) }}
      onBlur={() => setEngaged(false)}
    >
      {/* Soft glow behind him (lilac in light mode, indigo in dark mode) */}
      <motion.div
        aria-hidden="true"
        animate={{ opacity: up ? 1 : 0, scale: up ? 1 : 0.7 }}
        transition={{ duration: 0.6 }}
        className="pointer-events-none absolute bottom-0 left-1/2 h-[85%] w-[100%] -translate-x-1/2 rounded-full bg-fuchsia-400/25 blur-2xl dark:bg-indigo-500/35"
      />

      {/* Speech bubble: only while he waves, small, well to the left of his head with a gap, so the hearts (which float up on the right) stay clear (clear of the floating icons) */}
      <AnimatePresence>
        {waving && (
          <motion.div
            key={greeting}
            aria-hidden="true"
            initial={{ opacity: 0, scale: 0.6, y: 6 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.8 }}
            transition={{ type: "spring", stiffness: 380, damping: 20 }}
            style={{ transformOrigin: "80% 100%" }}
            className="pointer-events-none absolute bottom-full right-[66%] z-30 mb-3"
          >
            <div className="relative whitespace-nowrap rounded-full border border-slate-200 bg-white px-2.5 py-0.5 text-[10px] font-bold text-slate-700 shadow-md md:text-[11px] dark:border-white/10 dark:bg-card dark:text-foreground">
              {GREETINGS[greeting]}
              <span className="absolute right-3.5 top-full -mt-[3px] h-1.5 w-1.5 rotate-45 border-b border-r border-slate-200 bg-white dark:border-white/10 dark:bg-card" />
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* The floor: only the bottom is clipped (at the card's top edge), so nothing of him ever shows below the card */}
      <div className="absolute inset-0" style={{ clipPath: "inset(-70% -45% 0 -45%)" }}>
        <motion.div
          initial={false}
          animate={{ y: bodyY }}
          transition={bodyTransition}
          className="absolute inset-x-0 top-0"
          style={{ aspectRatio: `${IMG_W} / ${IMG_H}` }}
        >
          <motion.div animate={hop} className="h-full w-full origin-bottom">
            <div
              ref={buddyRef}
              className="relative h-full w-full drop-shadow-[0_6px_8px_rgba(60,40,90,0.28)] transition-transform duration-200 hover:scale-[1.03] active:scale-95"
            >
              {/* eslint-disable @next/next/no-img-element */}
              <img src="/mascot/body.png" alt="" draggable={false} className="absolute inset-0 h-full w-full select-none" />

              {/* Eyes (drawn here so they can follow the cursor and blink) */}
              <svg viewBox={`0 0 ${IMG_W} ${IMG_H}`} aria-hidden="true" className="pointer-events-none absolute inset-0 h-full w-full">
                <g className="mascot-eyes">
                  <g style={{ transform: "translate(var(--eye-x, 0px), var(--eye-y, 0px))", transition: "transform 120ms ease-out" }}>
                    <ellipse cx="140" cy="94.5" rx="7.6" ry="8.4" fill="#120c0b" />
                    <ellipse cx="220.5" cy="91.5" rx="7.6" ry="8.4" fill="#120c0b" />
                    <circle cx="142.6" cy="91.4" r="2.6" fill="#fff" />
                    <circle cx="223.1" cy="88.4" r="2.6" fill="#fff" />
                    <circle cx="137.5" cy="98.5" r="1.2" fill="#fff" opacity="0.7" />
                    <circle cx="218" cy="95.5" r="1.2" fill="#fff" opacity="0.7" />
                  </g>
                </g>
              </svg>

              <motion.img
                src="/mascot/arm-l.png" alt="" draggable={false}
                initial={false} animate={leftArm} transition={armTransition}
                style={{ transformOrigin: L_PIVOT }}
                className="pointer-events-none absolute inset-0 h-full w-full select-none"
              />
              <motion.img
                src="/mascot/arm-r.png" alt="" draggable={false}
                initial={false} animate={rightArm} transition={armTransition}
                style={{ transformOrigin: R_PIVOT }}
                className="pointer-events-none absolute inset-0 h-full w-full select-none"
              />
              {/* eslint-enable @next/next/no-img-element */}

              <button
                type="button"
                onClick={cheer}
                aria-label="Say hi to the MCF buddy"
                className="absolute inset-x-[14%] inset-y-0 cursor-pointer rounded-[40%] outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
              />
            </div>
          </motion.div>
        </motion.div>
      </div>

      {/* Hearts on click (outside the clipped floor so they can float above the head) */}
      <AnimatePresence>
        {hearts.map((heart) => (
          <motion.span
            key={heart.id}
            aria-hidden="true"
            initial={{ opacity: 0, y: 0, scale: 0.4 }}
            animate={{ opacity: [0, 1, 0], y: -46, x: heart.x, scale: [0.4, 1.1, 0.9] }}
            transition={{ duration: 1.2, ease: "easeOut" }}
            className="pointer-events-none absolute bottom-[90%] left-1/2 -ml-2 z-20"
          >
            <Heart className="h-4 w-4 fill-pink-400 text-pink-400" />
          </motion.span>
        ))}
      </AnimatePresence>
    </motion.div>
  )
}
