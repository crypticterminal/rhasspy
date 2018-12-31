<template>
    <div class="container">
        <form class="form" v-on:submit.prevent="saveProfile">
            <h2>{{ this.profile }}</h2>

            <div class="form-group">
                <div class="form-row">
                    <button type="submit" class="btn btn-primary"
                            v-bind:class="{ 'btn-danger': profileSettingsDirty }">Save Profile</button>
                </div>
            </div>

            <div class="form-group">
                <div class="form-row">
                    <textarea id="profile-settings" class="form-control" style="border-width: 3px" type="text" rows="15" v-model="profileSettings" v-bind:class="{ 'border-danger': profileSettingsDirty }" @input="profileSettingsDirty=true"></textarea>
                </div>
            </div>

            <div class="form-group">
                <div class="form-row">
                    <button type="submit" class="btn btn-primary"
                            v-bind:class="{ 'btn-danger': profileSettingsDirty }">Save Profile</button>
                </div>
            </div>
        </form>

        <hr />

        <form class="form" v-on:submit.prevent="saveDefaults">
            <h2>Defaults</h2>

            <div class="form-group">
                <div class="form-row">
                    <button type="submit" class="btn btn-primary"
                            v-bind:class="{ 'btn-danger': defaultSettingsDirty }">Save Defaults</button>
                </div>
            </div>

            <textarea id="default-settings" class="form-control" type="text" rows="15" v-model="defaultSettings"></textarea>

            <div class="form-group">
                <div class="form-row">
                    <button type="submit" class="btn btn-primary"
                            v-bind:class="{ 'btn-danger': defaultSettingsDirty }">Save Defaults</button>
                </div>
            </div>
        </form>
    </div> <!-- container -->
</template>

<script>
 import ProfileService from '@/services/ProfileService'

 export default {
     name: 'AdvancedSettings',
     props: {
         profile : String
     },
     data: function () {
         return {
             profileSettings: '',
             profileSettingsDirty: false,

             defaultSettings: '',
             defaultSettingsDirty: false
         }
     },

     methods: {
         refreshSettings: function() {
             ProfileService.getProfileSettings(this.profile, 'profile')
                           .then(request => {
                               this.profileSettings = JSON.stringify(request.data, null, 4)
                           })
                           .catch(err => this.$parent.alert(err.response.data, 'danger'))
         },

         refreshDefaults: function() {
             ProfileService.getProfileSettings(this.profile, 'defaults')
                           .then(request => {
                               this.defaultSettings = JSON.stringify(request.data, null, 4)
                           })
                           .catch(err => this.$parent.alert(err.response.data, 'danger'))
         },

         saveProfile: function() {
             this.$parent.beginAsync()
             ProfileService.updateProfileSettings(this.profile, this.profileSettings)
                 .then(request => this.$parent.alert(request.data, 'success'))
                 .catch(err => this.$parent.alert(err.response.data, 'danger'))
                 .then(() => {
                     this.$parent.endAsync()
                     this.profileSettingsDirty = false
                 })
         },

         saveDefaults: function() {
             this.$parent.beginAsync()
             ProfileService.updateDefaultSettings(this.defaultSettings)
                 .then(request => this.$parent.alert(request.data, 'success'))
                 .catch(err => this.$parent.alert(err.response.data, 'danger'))
                 .then(() => {
                     this.$parent.endAsync()
                     this.defaultSettingsDirty = false
                 })
         }
     },

     mounted: function() {
         this.refreshSettings()
         this.refreshDefaults()
     },

     watch: {
         profile() {
             this.refreshSettings()
             this.refreshDefaults()
         }
     }
 }
</script>

<!-- Add "scoped" attribute to limit CSS to this component only -->
<style scoped>
</style>