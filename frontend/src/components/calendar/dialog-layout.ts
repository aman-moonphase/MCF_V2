// Shared layout for the calendar planning dialogs (Add to Calendar, Reschedule, Cancel plan): constrained to the
// viewport (safe areas included) with a fixed header and footer and an independently scrolling body.

export const dialogContent =
  'flex max-h-[calc(100dvh_-_2rem_-_env(safe-area-inset-top)_-_env(safe-area-inset-bottom))] w-[calc(100vw_-_1.5rem)] max-w-[600px] flex-col gap-0 overflow-hidden rounded-xl p-0 sm:w-[calc(100vw_-_2rem)] sm:rounded-xl';
export const dialogHeader = 'shrink-0 space-y-1 border-b border-border/60 px-5 pb-3 pr-12 pt-5 text-left sm:px-6 sm:pr-12';
export const dialogBody = 'min-h-0 flex-1 space-y-5 overflow-y-auto overscroll-contain px-5 py-4 sm:px-6';
export const dialogFooter =
  'flex shrink-0 items-center justify-end gap-2 border-t border-border/60 bg-background px-5 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 sm:px-6';
export const sectionTitle = 'text-xs font-semibold uppercase tracking-wider text-muted-foreground';
export const inputField = 'h-10 bg-background/50';
export const NOTES_MAX = 2000;

export const LONG_DATE_TIME: Intl.DateTimeFormatOptions = {
  weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit',
};
