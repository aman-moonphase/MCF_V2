import { useState, useEffect } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { ScheduleService } from '@/lib/services/schedule.service';
import { ProjectService } from '@/lib/project-service';
import { CreateScheduleRequest, UpdateScheduleRequest, ScheduleWithProject } from '@/types/schedule';
import { Project } from '@/types/project';
import { toast } from 'sonner';

interface ScheduleDialogProps {
  projectId?: string;
  isOpen: boolean;
  onClose: () => void;
  onScheduled: () => void;
  existingSchedule?: ScheduleWithProject;
  initialDate?: string;
}

export function ScheduleDialog({ projectId, isOpen, onClose, onScheduled, existingSchedule, initialDate }: ScheduleDialogProps) {
  const [loading, setLoading] = useState(false);
  const [platform, setPlatform] = useState('LinkedIn');
  const [scheduledDate, setScheduledDate] = useState('');
  const [scheduledTime, setScheduledTime] = useState('09:00');
  const [selectedProjectId, setSelectedProjectId] = useState<string>('');
  const [eligibleProjects, setEligibleProjects] = useState<Project[]>([]);

  useEffect(() => {
    if (isOpen) {
      if (existingSchedule) {
        setPlatform(existingSchedule.platform);
        const dateObj = new Date(existingSchedule.scheduledAt);
        // adjust for timezone offset to get local YYYY-MM-DD
        const offset = dateObj.getTimezoneOffset();
        const localDate = new Date(dateObj.getTime() - (offset * 60 * 1000));
        setScheduledDate(localDate.toISOString().split('T')[0]);
        setScheduledTime(localDate.toISOString().split('T')[1].substring(0, 5));
        setSelectedProjectId(existingSchedule.projectId);
      } else {
        setPlatform('LinkedIn');
        setScheduledDate(initialDate || new Date().toISOString().split('T')[0]);
        setScheduledTime('09:00');
        setSelectedProjectId(projectId || '');
      }

      if (!projectId && !existingSchedule) {
        // Fetch eligible projects
        loadEligibleProjects();
      }
    }
  }, [isOpen, existingSchedule, projectId, initialDate]);

  const loadEligibleProjects = async () => {
    try {
      const projects = await ProjectService.getProjects();
      const eligible = projects.filter(p => 
        p.stages?.find(s => s.type === 'final-script' && s.status === 'Completed')
      );
      setEligibleProjects(eligible);
      if (eligible.length > 0 && !selectedProjectId) {
        setSelectedProjectId(eligible[0].id);
      }
    } catch (e) {
      console.error(e);
      toast.error('Failed to load eligible projects');
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!scheduledDate || !scheduledTime) {
      toast.error('Please select both date and time');
      return;
    }

    if (!selectedProjectId) {
      toast.error('Please select a project');
      return;
    }

    setLoading(true);
    try {
      const scheduledAt = new Date(`${scheduledDate}T${scheduledTime}:00`).toISOString();
      
      if (existingSchedule) {
        const payload: UpdateScheduleRequest = {
          platform,
          scheduledAt,
          status: existingSchedule.status
        };
        await ScheduleService.updateSchedule(existingSchedule.id, payload);
        toast.success('Calendar entry updated');
      } else {
        const payload: CreateScheduleRequest = {
          projectId: selectedProjectId,
          platform,
          scheduledAt,
        };
        await ScheduleService.createSchedule(payload);
        toast.success('Added to the calendar');
      }
      
      onScheduled();
      onClose();
    } catch (error: any) {
      console.error('Schedule error:', error);
      toast.error(error?.message || 'Failed to save the calendar entry');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open: boolean) => !open && onClose()}>
      <DialogContent className="sm:max-w-[425px] glass-panel border-white/10 shadow-2xl p-6 rounded-xl">
        <DialogHeader className="mb-4">
          <DialogTitle className="text-2xl font-bold text-gradient">
            {existingSchedule ? 'Edit legacy calendar entry' : 'Add legacy calendar entry'}
          </DialogTitle>
          <DialogDescription className="text-muted-foreground/80">
            For projects from the earlier script workflow. This records a planned date only — MCF does not publish anything.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-5">
          
          {!projectId && !existingSchedule && (
             <div className="space-y-2">
               <Label htmlFor="project" className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Project</Label>
               <Select value={selectedProjectId} onValueChange={setSelectedProjectId}>
                 <SelectTrigger className="bg-background/50 border-white/10 hover:border-primary/50 transition-colors h-11">
                   <SelectValue placeholder="Select a project" />
                 </SelectTrigger>
                 <SelectContent className="glass-panel border-white/10">
                   {eligibleProjects.length === 0 && <SelectItem value="none" disabled>No legacy projects with a completed final script</SelectItem>}
                   {eligibleProjects.map(p => (
                     <SelectItem key={p.id} value={p.id} className="cursor-pointer">{p.title}</SelectItem>
                   ))}
                 </SelectContent>
               </Select>
             </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="platform" className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Platform</Label>
            <Select value={platform} onValueChange={setPlatform}>
              <SelectTrigger className="bg-background/50 border-white/10 hover:border-primary/50 transition-colors h-11">
                <SelectValue placeholder="Select platform" />
              </SelectTrigger>
              <SelectContent className="glass-panel border-white/10">
                <SelectItem value="LinkedIn" className="cursor-pointer">LinkedIn</SelectItem>
                <SelectItem value="Twitter" className="cursor-pointer">Twitter / X</SelectItem>
                <SelectItem value="Instagram" className="cursor-pointer">Instagram</SelectItem>
                <SelectItem value="Blog" className="cursor-pointer">Blog / Website</SelectItem>
                <SelectItem value="TikTok" className="cursor-pointer">TikTok</SelectItem>
                <SelectItem value="YouTube" className="cursor-pointer">YouTube</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="date" className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Date</Label>
              <Input
                id="date"
                type="date"
                value={scheduledDate}
                onChange={(e) => setScheduledDate(e.target.value)}
                min={new Date().toISOString().split('T')[0]}
                required
                className="bg-background/50 border-white/10 hover:border-primary/50 transition-colors h-11"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="time" className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Time</Label>
              <Input
                id="time"
                type="time"
                value={scheduledTime}
                onChange={(e) => setScheduledTime(e.target.value)}
                required
                className="bg-background/50 border-white/10 hover:border-primary/50 transition-colors h-11"
              />
            </div>
          </div>

          <DialogFooter className="pt-6 sm:justify-between flex-row">
            <Button type="button" variant="ghost" onClick={onClose} disabled={loading} className="hover:bg-destructive/10 hover:text-destructive">
              Cancel
            </Button>
            <Button type="submit" disabled={loading} className="bg-primary hover:bg-primary/90 text-primary-foreground shadow-lg shadow-primary/25 min-w-[120px]">
              {loading ? 'Saving...' : (existingSchedule ? 'Save changes' : 'Add to calendar')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
