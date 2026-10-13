export {}
declare module 'vue' {
  export interface GlobalComponents {
    HelpTip: (typeof import('./HelpTip.vue'))['default']
    FieldLabel: (typeof import('./FieldLabel.vue'))['default']
  }
}
