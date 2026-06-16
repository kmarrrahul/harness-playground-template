function skillsMixin() {
  return {
    skillsModalOpen: false,
    availableSkills: { bundled: [], user_uploaded: [] },
    skillsLoading: false,
    skillUploadError: '',
    
    skillUploadType: 'text', // 'text' or 'zip'
    textSkillId: '',
    textSkillContent: '',

    openSkillsModal() {
      this.skillsModalOpen = true;
      this.fetchSkills();
    },

    closeSkillsModal() {
      this.skillsModalOpen = false;
      this.skillUploadError = '';
      this.textSkillId = '';
      this.textSkillContent = '';
    },

    async fetchSkills() {
      this.skillsLoading = true;
      try {
        const token = this.getActiveToken();
        const res = await fetch('api/skills', {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        if (res.ok) {
          const data = await res.json();
          this.availableSkills = data;
          
          // Auto-enable any skills with default_enabled=true that are not already tracked
          for (const s of data.bundled.concat(data.user_uploaded)) {
            if (s.default_enabled && !this.enabledSkills.includes(s.id)) {
              this.enabledSkills.push(s.id);
            }
          }
        }
      } catch (e) {
        console.error('Failed to fetch skills', e);
      } finally {
        this.skillsLoading = false;
      }
    },

    async uploadTextSkill() {
      if (!this.textSkillId.trim() || !this.textSkillContent.trim()) {
        this.skillUploadError = 'Please provide both a Skill ID and instructions.';
        return;
      }
      
      this.skillsLoading = true;
      this.skillUploadError = '';
      
      try {
        const token = this.getActiveToken();
        const res = await fetch('api/skills/text', {
          method: 'POST',
          headers: { 
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            skill_id: this.textSkillId,
            content: this.textSkillContent
          })
        });
        const data = await res.json();
        if (data.success) {
          this.enabledSkills.push(data.skill_id); // Auto-enable on upload
          this.textSkillId = '';
          this.textSkillContent = '';
          await this.fetchSkills();
        } else {
          this.skillUploadError = data.error || 'Upload failed';
        }
      } catch (e) {
        this.skillUploadError = e.message;
      } finally {
        this.skillsLoading = false;
      }
    },

    async uploadSkill(event) {
      const file = event.target.files[0];
      if (!file) return;
      if (!file.name.endsWith('.zip')) {
        this.skillUploadError = 'Please upload a .zip file containing the skill.';
        return;
      }
      
      this.skillsLoading = true;
      this.skillUploadError = '';
      const formData = new FormData();
      formData.append('file', file);
      
      try {
        const token = this.getActiveToken();
        const res = await fetch('api/skills/upload', {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${token}` },
          body: formData
        });
        const data = await res.json();
        if (data.success) {
          this.enabledSkills.push(data.skill_id); // Auto-enable on upload
          await this.fetchSkills();
        } else {
          this.skillUploadError = data.error || 'Upload failed';
        }
      } catch (e) {
        this.skillUploadError = e.message;
      } finally {
        this.skillsLoading = false;
        event.target.value = ''; // Reset file input
      }
    },

    async deleteSkill(skillId) {
      if (!confirm('Are you sure you want to delete this skill?')) return;
      
      try {
        const token = this.getActiveToken();
        const res = await fetch(`api/skills/${skillId}`, {
          method: 'DELETE',
          headers: { 'Authorization': `Bearer ${token}` }
        });
        if (res.ok) {
          this.enabledSkills = this.enabledSkills.filter(id => id !== skillId);
          await this.fetchSkills();
        }
      } catch (e) {
        console.error('Failed to delete skill', e);
      }
    },

    toggleSkill(skillId) {
      if (this.enabledSkills.includes(skillId)) {
        this.enabledSkills = this.enabledSkills.filter(id => id !== skillId);
      } else {
        this.enabledSkills.push(skillId);
      }
    }
  };
}
