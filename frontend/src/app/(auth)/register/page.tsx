"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiClient } from "@/lib/api-client";
import { Layers, ArrowRight, Loader2, Sparkles } from "lucide-react";

export default function RegisterPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const router = useRouter();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    setIsLoading(true);

    try {
      await apiClient.post("/auth/register", {
        email,
        password,
        is_active: true,
        is_superuser: false
      });
      // Redirect to login after successful registration
      router.push("/login");
    } catch (err: any) {
      setError(err.message || "Failed to register. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="relative min-h-screen flex items-center justify-center overflow-hidden bg-background selection:bg-primary/30">
      {/* Dynamic Background Elements */}
      <div className="absolute inset-0 z-0">
        <div className="absolute top-[10%] right-[-10%] w-[40%] h-[40%] rounded-full bg-indigo-500/20 blur-[120px] animate-pulse" />
        <div className="absolute bottom-[-10%] left-[-10%] w-[50%] h-[50%] rounded-full bg-emerald-500/15 blur-[150px] animate-pulse" style={{ animationDelay: '2s' }} />
        <div className="absolute top-[30%] left-[20%] w-[30%] h-[30%] rounded-full bg-violet-500/15 blur-[100px] animate-pulse" style={{ animationDelay: '4s' }} />
        <div className="absolute inset-0 bg-grid bg-[size:40px_40px] opacity-[0.03] dark:opacity-[0.05]" />
      </div>

      <div className="w-full max-w-md px-4 z-10 relative mt-12 mb-12">
        <div className="mb-8 flex flex-col items-center justify-center space-y-4 animate-in fade-in slide-in-from-bottom-4 duration-700">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 via-violet-500 to-emerald-500 text-white shadow-[0_0_30px_rgba(99,102,241,0.5)]">
            <Layers className="h-8 w-8" />
          </div>
          <div className="text-center space-y-2">
            <h1 className="text-3xl font-black tracking-tight text-foreground">
              Create an account
            </h1>
            <p className="text-muted-foreground font-medium">
              Join the content studio platform
            </p>
          </div>
        </div>

        <div className="backdrop-blur-xl bg-white/60 dark:bg-card/40 border border-white/20 dark:border-white/10 shadow-[0_8px_32px_rgba(0,0,0,0.08)] dark:shadow-[0_8px_32px_rgba(0,0,0,0.2)] rounded-3xl p-8 animate-in fade-in slide-in-from-bottom-8 duration-700 delay-150 fill-mode-both">
          <form onSubmit={handleSubmit} className="space-y-6">
            {error && (
              <div className="bg-destructive/10 border border-destructive/20 text-destructive text-sm p-4 rounded-xl flex items-start gap-3 animate-in fade-in zoom-in-95">
                <span className="flex-1">{error}</span>
              </div>
            )}
            
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="email" className="text-foreground/80 font-semibold ml-1">Email</Label>
                <Input 
                  id="email" 
                  type="email" 
                  placeholder="name@example.com" 
                  required 
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="h-12 px-4 rounded-xl bg-white/50 dark:bg-black/20 border-slate-200 dark:border-white/10 focus-visible:ring-indigo-500 focus-visible:border-indigo-500 transition-all shadow-sm"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="password" className="text-foreground/80 font-semibold ml-1">Password</Label>
                <Input 
                  id="password" 
                  type="password" 
                  placeholder="••••••••"
                  required 
                  minLength={8}
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="h-12 px-4 rounded-xl bg-white/50 dark:bg-black/20 border-slate-200 dark:border-white/10 focus-visible:ring-indigo-500 focus-visible:border-indigo-500 transition-all shadow-sm"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="confirmPassword" className="text-foreground/80 font-semibold ml-1">Confirm Password</Label>
                <Input 
                  id="confirmPassword" 
                  type="password" 
                  placeholder="••••••••"
                  required 
                  minLength={8}
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className="h-12 px-4 rounded-xl bg-white/50 dark:bg-black/20 border-slate-200 dark:border-white/10 focus-visible:ring-indigo-500 focus-visible:border-indigo-500 transition-all shadow-sm"
                />
              </div>
            </div>

            <Button 
              type="submit" 
              className="w-full h-12 rounded-xl bg-gradient-to-r from-indigo-500 to-violet-500 hover:from-indigo-600 hover:to-violet-600 text-white font-semibold text-base shadow-md hover:shadow-lg hover:-translate-y-0.5 transition-all group" 
              disabled={isLoading}
            >
              {isLoading ? (
                <div className="flex items-center gap-2">
                  <Loader2 className="h-5 w-5 animate-spin" />
                  <span>Creating account...</span>
                </div>
              ) : (
                <div className="flex items-center justify-center gap-2">
                  <span>Sign up</span>
                  <ArrowRight className="h-5 w-5 group-hover:translate-x-1 transition-transform" />
                </div>
              )}
            </Button>
          </form>

          <div className="mt-8 text-center">
            <p className="text-sm text-muted-foreground font-medium">
              Already have an account?{" "}
              <Link href="/login" className="text-indigo-500 hover:text-indigo-600 dark:hover:text-indigo-400 font-semibold transition-colors hover:underline underline-offset-4">
                Sign in instead
              </Link>
            </p>
          </div>
        </div>
        
        {/* Decorative element */}
        <div className="mt-8 flex items-center justify-center gap-2 text-sm text-muted-foreground/60 font-medium animate-in fade-in duration-1000 delay-500 fill-mode-both">
          <Sparkles className="h-4 w-4" />
          <span>MCF Content Studio</span>
        </div>
      </div>
    </div>
  );
}
