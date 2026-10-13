"use client"

import * as React from "react"
import { toast } from 'sonner';
import { motion, AnimatePresence } from "framer-motion"
import { Paperclip, Link2, Sparkles, Settings2, ArrowRight, FileText, Mail, Briefcase, MessageSquare, Code } from "lucide-react"
import { cn } from "@/lib/utils"
import { useRouter } from "next/navigation"
import { ProjectService } from "@/lib/project-service"
import { ContentRecipes } from "./ContentRecipes"
import { HeroMascot } from "./HeroMascot"

const LinkedinIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" {...props}>
    <path d="M19 0h-14c-2.761 0-5 2.239-5 5v14c0 2.761 2.239 5 5 5h14c2.762 0 5-2.239 5-5v-14c0-2.761-2.238-5-5-5zm-11 19h-3v-11h3v11zm-1.5-12.268c-.966 0-1.75-.79-1.75-1.764s.784-1.764 1.75-1.764 1.75.79 1.75 1.764-.783 1.764-1.75 1.764zm13.5 12.268h-3v-5.604c0-3.368-4-3.113-4 0v5.604h-3v-11h3v1.765c1.396-2.586 7-2.777 7 2.476v6.759z"/>
  </svg>
)

const XIcon = (props: React.SVGProps<SVGSVGElement>) => (
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" {...props}>
    <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.008 5.922H5.078z" />
  </svg>
)

export function Composer() {
  const [text, setText] = React.useState("")
  const [isFocused, setIsFocused] = React.useState(false)
  const [isSubmitting, setIsSubmitting] = React.useState(false)
  const router = useRouter()

  const showOptions = text.length > 5

  const fileInputRef = React.useRef<HTMLInputElement>(null)
  const [selectedFile, setSelectedFile] = React.useState<File | null>(null)

  // Typewriter Placeholder Logic
  const placeholders = React.useMemo(() => [
    "Paste a research URL...",
    "Drop a document...",
    "Start typing a raw idea...",
    "Draft a LinkedIn post...",
    "Write a product launch announcement..."
  ], []);
  const [placeholderText, setPlaceholderText] = React.useState("");

  React.useEffect(() => {
    let i = 0;
    let j = 0;
    let isDeleting = false;
    let timeoutId: NodeJS.Timeout;

    const type = () => {
      const currentWord = placeholders[i];
      if (isDeleting) {
        setPlaceholderText(currentWord.substring(0, j - 1));
        j--;
        if (j === 0) {
          isDeleting = false;
          i = (i + 1) % placeholders.length;
          timeoutId = setTimeout(type, 500);
        } else {
          timeoutId = setTimeout(type, 30);
        }
      } else {
        setPlaceholderText(currentWord.substring(0, j + 1));
        j++;
        if (j === currentWord.length) {
          isDeleting = true;
          timeoutId = setTimeout(type, 2000);
        } else {
          timeoutId = setTimeout(type, 80);
        }
      }
    };
    
    timeoutId = setTimeout(type, 500);
    return () => clearTimeout(timeoutId);
  }, [placeholders]);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setSelectedFile(e.target.files[0])
      setText(`File: ${e.target.files[0].name}`)
    }
  }

  const handleInitialize = async () => {
    if ((!text.trim() && !selectedFile) || isSubmitting) return
    try {
      setIsSubmitting(true)
      
      const isUrl = text.trim().startsWith('http://') || text.trim().startsWith('https://');
      const isFile = !!selectedFile;
      
      let title = 'Idea: ' + text.trim().substring(0, 30) + '...';
      let sourceType = 'Text Idea';
      if (isUrl) {
        title = 'Analysis: ' + new URL(text.trim()).hostname;
        sourceType = 'URL';
      } else if (isFile && selectedFile) {
        title = 'Document: ' + selectedFile.name;
        sourceType = 'File';
      } else {
        const projectNameMatch = text.match(/^\s*(?:Project\s*Name|Project\s*Title|Title)\s*:\s*([^\r\n]+)/im);
        if (projectNameMatch && projectNameMatch[1].trim()) {
          title = projectNameMatch[1].trim();
        }
      }

      // 1. Create the project
      const rawSourceReference = isFile && selectedFile ? selectedFile.name : text.trim();
      const project = await ProjectService.createProject({ 
        title,
        description: isFile && selectedFile ? selectedFile.name : text.trim(),
        sourceType,
        sourceReference: rawSourceReference.length > 495 ? rawSourceReference.substring(0, 495) + '...' : rawSourceReference,
      })

      // 2. Ingest the source
      const formData = new FormData();
      if (isFile && selectedFile) {
        formData.append('source_type', 'pdf');
        formData.append('file', selectedFile);
      } else if (isUrl) {
        formData.append('source_type', 'url');
        formData.append('content', text.trim());
      } else {
        formData.append('source_type', 'text');
        formData.append('content', text.trim());
      }

      await ProjectService.ingestSource(project.id, formData);

      // 3. Redirect
      router.push(`/projects/${project.id}`)
    } catch (error) {
      console.error("Failed to initialize project:", error)
      toast.error(`Could not create the project: ${error instanceof Error ? error.message : String(error)}`)
      setIsSubmitting(false)
    }
  }

  const [selectedPlatforms, setSelectedPlatforms] = React.useState<string[]>([])
  const [selectedTones, setSelectedTones] = React.useState<string[]>([])

  const togglePlatform = (name: string) => {
    setSelectedPlatforms(prev => 
      prev.includes(name) ? prev.filter(p => p !== name) : [...prev, name]
    )
  }

  const toggleTone = (name: string) => {
    setSelectedTones(prev => 
      prev.includes(name) ? prev.filter(t => t !== name) : [...prev, name]
    )
  }

  return (
    <motion.div 
      initial={{ opacity: 0, filter: 'blur(10px)' }}
      animate={{ opacity: 1, filter: 'blur(0px)' }}
      transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
      className="flex flex-col w-full max-w-4xl"
    >
      <div className="relative flex flex-col md:flex-row items-center justify-between w-full mb-4 gap-8">
        <div className="flex flex-col items-start w-full md:w-auto z-10">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.1, ease: [0.16, 1, 0.3, 1] }}
            className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-primary/10 border border-primary/20 text-xs font-semibold mb-6 shadow-sm"
          >
            <Sparkles className="h-4 w-4 text-primary" />
            <span className="text-primary text-sm font-bold tracking-tight">Multimodal Content Engine</span>
          </motion.div>
          
          <motion.h1 
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.2, ease: [0.16, 1, 0.3, 1] }}
            className="text-4xl sm:text-5xl md:text-6xl font-extrabold tracking-tighter text-foreground leading-[1.15] mb-[104px] md:mb-0"
          >
            What are you <br />
            <span className="text-transparent bg-clip-text animate-gradient-flow bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500 dark:from-indigo-400 dark:via-purple-400 dark:to-pink-400">
              making today?
            </span>
          </motion.h1>
        </div>

        {/* Animated Hero Graphic */}
        <div className="hidden md:flex relative h-[180px] w-[260px] lg:w-[320px] items-center justify-center pointer-events-none">
          {/* Glowing Background Orbs */}
          <motion.div 
            animate={{ scale: [1, 1.1, 1], opacity: [0.3, 0.5, 0.3] }}
            transition={{ duration: 6, repeat: Infinity, ease: "easeInOut" }}
            className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-32 h-32 bg-indigo-500/40 rounded-full blur-3xl"
          />
          <motion.div 
            animate={{ scale: [1, 1.2, 1], opacity: [0.2, 0.4, 0.2] }}
            transition={{ duration: 7, delay: 1, repeat: Infinity, ease: "easeInOut" }}
            className="absolute top-1/2 left-[30%] -translate-x-1/2 -translate-y-1/2 w-24 h-24 bg-pink-500/30 rounded-full blur-2xl"
          />
          <motion.div 
            animate={{ scale: [1, 1.1, 1], opacity: [0.2, 0.4, 0.2] }}
            transition={{ duration: 5, delay: 2, repeat: Infinity, ease: "easeInOut" }}
            className="absolute top-[40%] left-[70%] -translate-x-1/2 -translate-y-1/2 w-28 h-28 bg-purple-500/30 rounded-full blur-2xl"
          />

          {/* Floating UI Cards */}
          <motion.div 
            animate={{ y: [-5, 5, -5], rotate: [-2, 2, -2] }}
            transition={{ duration: 5, repeat: Infinity, ease: "easeInOut" }}
            className="absolute left-[0%] top-[38%] w-14 h-[72px] rounded-xl bg-white/5 border border-slate-200 dark:border-white/10 shadow-lg backdrop-blur-md flex items-center justify-center z-10"
          >
            <FileText className="w-6 h-6 text-indigo-500 dark:text-indigo-400" />
          </motion.div>

          <motion.div 
            animate={{ y: [5, -5, 5], rotate: [2, -2, 2] }}
            transition={{ duration: 6, delay: 0.5, repeat: Infinity, ease: "easeInOut" }}
            className="absolute left-[15%] top-[2%] w-[72px] h-[88px] rounded-2xl bg-white/5 border border-slate-200 dark:border-white/10 shadow-xl backdrop-blur-md flex items-center justify-center z-20"
          >
            <Sparkles className="w-8 h-8 text-purple-500 dark:text-purple-400" />
          </motion.div>

          <motion.div 
            animate={{ y: [-8, 8, -8], rotate: [-4, 4, -4] }}
            transition={{ duration: 7, delay: 1.5, repeat: Infinity, ease: "easeInOut" }}
            className="absolute left-[40%] top-[-4%] w-12 h-12 rounded-full bg-white/5 border border-slate-200 dark:border-white/10 shadow-lg backdrop-blur-md flex items-center justify-center z-10"
          >
            <Link2 className="w-6 h-6 text-pink-500 dark:text-pink-400" />
          </motion.div>
        </div>

        {/* The buddy peeks up from the top edge of the composer: this row's bottom edge plus its mb-4 gap */}
        <HeroMascot className="absolute -bottom-4 right-6 md:right-12 z-0 w-[96px] md:w-[124px]" />
      </div>

      {/* Main Composer Area */}
      <motion.div 
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, delay: 0.3, ease: [0.16, 1, 0.3, 1] }}
        className={cn(
          "group relative flex flex-col rounded-3xl transition-all duration-500 bg-white dark:bg-[#111116] border border-slate-200 dark:border-white/10 shadow-sm dark:shadow-lg",
          isFocused 
            ? "ring-1 ring-indigo-500/30 dark:ring-indigo-400/50 shadow-[0_8px_30px_rgb(0,0,0,0.04)] dark:shadow-[0_0_40px_-10px_rgba(99,102,241,0.2)] scale-[1.01] border-indigo-500/30 dark:border-transparent" 
            : "hover:border-slate-300 dark:hover:border-indigo-400/30 hover:shadow-md dark:hover:shadow-xl"
        )}
      >
        {/* Animated glowing top border */}
        <div className="absolute inset-x-0 top-0 h-[2px] bg-gradient-to-r from-transparent via-indigo-500/50 to-transparent rounded-t-3xl opacity-50 group-hover:opacity-100 transition-opacity" />
        
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          placeholder={placeholderText}
          className="min-h-[100px] sm:min-h-[140px] w-full resize-none bg-transparent p-5 sm:p-8 text-lg sm:text-xl font-medium tracking-tight text-foreground placeholder:text-muted-foreground focus:outline-none selection:bg-indigo-500/30"
        />

        <div className="flex items-center justify-between p-3 sm:p-4 pl-4 sm:pl-6 border-t border-slate-100 dark:border-white/5 bg-slate-50/50 dark:bg-black/20 rounded-b-3xl">
          <div className="flex items-center gap-2">
            <button 
              onClick={() => fileInputRef.current?.click()}
              className="flex items-center justify-center h-10 w-10 rounded-full text-slate-400 dark:text-muted-foreground hover:text-indigo-500 dark:hover:text-indigo-400 hover:bg-indigo-500/10 transition-all duration-300"
              title="Attach a document"
            >
              <Paperclip className="h-5 w-5" />
            </button>
            <input 
              type="file" 
              ref={fileInputRef} 
              style={{ display: 'none' }} 
              accept="application/pdf"
              onChange={handleFileChange}
            />
          </div>
          
          <button 
            onClick={handleInitialize}
            disabled={isSubmitting || (text.length === 0 && !selectedFile)}
            className={cn(
              "group/btn relative flex items-center justify-center gap-2 h-11 sm:h-12 rounded-full px-6 sm:px-8 text-sm sm:text-base font-bold transition-all duration-300 overflow-hidden",
              (text.length > 0 || selectedFile) && !isSubmitting
                ? "bg-zinc-900 text-white dark:bg-white dark:text-zinc-900 shadow-md hover:shadow-lg hover:scale-[1.02] active:scale-95 w-full sm:w-auto" 
                : "bg-slate-100 dark:bg-muted text-slate-400 dark:text-muted-foreground cursor-not-allowed shadow-none w-full sm:w-auto border border-slate-200 dark:border-border"
            )}
          >
            {/* SVG Gradient Definition */}
            <svg width="0" height="0" className="absolute">
              <linearGradient id="sparkle-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop stopColor="#6366f1" offset="0%" />
                <stop stopColor="#a855f7" offset="50%" />
                <stop stopColor="#ec4899" offset="100%" />
              </linearGradient>
            </svg>

            <div className="relative z-10 flex items-center gap-2">
              {isSubmitting ? (
                <div className="h-5 w-5 rounded-full border-2 border-current border-t-transparent animate-spin" />
              ) : (
                <Sparkles 
                  className="h-5 w-5" 
                  style={{ stroke: (text.length > 0 || selectedFile) && !isSubmitting ? "url(#sparkle-gradient)" : undefined }} 
                />
              )}
              <span>{isSubmitting ? 'Initializing...' : 'Initialize AI'}</span>
              {!isSubmitting && (
                <ArrowRight className="h-5 w-5 opacity-0 -ml-5 group-hover/btn:opacity-100 group-hover/btn:ml-0 transition-all duration-300" />
              )}
            </div>
          </button>
        </div>
      </motion.div>


      <ContentRecipes onSelect={setText} />
    </motion.div>
  )
}
