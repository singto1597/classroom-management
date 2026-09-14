# classroom-management_web-announcement_ts

This template should help get you started developing with Vue 3 in Vite.

## Recommended IDE Setup

[VS Code](https://code.visualstudio.com/) + [Vue (Official)](https://marketplace.visualstudio.com/items?itemName=Vue.volar) (and disable Vetur).

## Recommended Browser Setup

- Chromium-based browsers (Chrome, Edge, Brave, etc.):
  - [Vue.js devtools](https://chromewebstore.google.com/detail/vuejs-devtools/nhdogjmejiglipccpnnnanhbledajbpd)
  - [Turn on Custom Object Formatter in Chrome DevTools](http://bit.ly/object-formatters)
- Firefox:
  - [Vue.js devtools](https://addons.mozilla.org/en-US/firefox/addon/vue-js-devtools/)
  - [Turn on Custom Object Formatter in Firefox DevTools](https://fxdx.dev/firefox-devtools-custom-object-formatters/)

## Type Support for `.vue` Imports in TS

TypeScript cannot handle type information for `.vue` imports by default, so we replace the `tsc` CLI with `vue-tsc` for type checking. In editors, we need [Volar](https://marketplace.visualstudio.com/items?itemName=Vue.volar) to make the TypeScript language service aware of `.vue` types.

## Customize configuration

See [Vite Configuration Reference](https://vite.dev/config/).

## Project Setup

```sh
npm install
```

### Compile and Hot-Reload for Development

```sh
npm run dev
```

### Type-Check, Compile and Minify for Production

```sh
npm run build
```

### Run Unit Tests with [Vitest](https://vitest.dev/)

```sh
npm run test:unit
```

### Run End-to-End Tests with [Playwright](https://playwright.dev)

```sh
# Install browsers for the first run
npx playwright install

# When testing on CI, must build the project first
npm run build

# Runs the end-to-end tests
npm run test:e2e
# Runs the tests only on Chromium
npm run test:e2e -- --project=chromium
# Runs the tests of a specific file
npm run test:e2e -- tests/example.spec.ts
# Runs the tests in debug mode
npm run test:e2e -- --debug
```

### Lint with [ESLint](https://eslint.org/)

```sh
npm run lint
```

### ⚠️ อย่ารัน `npm run format` ทั้งโปรเจกต์

`src/` ทั้งหมด**ไม่เคยถูกจัดฟอร์มด้วย Prettier** ภายใต้ config ใดเลย ⇒ `npm run format`
จะ rewrite **67 ไฟล์ / ~4,000 บรรทัด** ที่ไม่เกี่ยวกับงานที่ทำอยู่ (วัดแล้ว: ต่างกัน 67 ไฟล์
ทั้ง `semi: true` และ `semi: false`) และไม่มี CI gate ตรวจ `prettier --check` ⇒ ไม่มีอะไรพังถ้าไม่จัด

- จัดฟอร์ม**ไฟล์เดียว** → `npx prettier --write <file>` (ถ้าผลลัพธ์ไม่ตรงสไตล์ repo ให้ override flag เช่น `--semi true`)
- ยึด **สไตล์ของโค้ดข้าง ๆ** เป็นหลัก — repo นี้ใช้เซมิโคลอน
- ต้องจัดฟอร์มทั้ง repo จริง ๆ → ทำเป็นคอมมิตแยกตอนไม่มีงานค้าง และขออนุญาตก่อน
- รายละเอียดเต็ม: `../docs/skills.md` → หัวข้อ "`npm run format` ไม่ปลอดภัยกับ repo นี้"
