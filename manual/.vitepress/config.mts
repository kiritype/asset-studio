import {defineConfig} from 'vitepress';

// Korean is written first and reviewed; the other languages follow it page by page.
const enGuide = [
  {text: 'Getting started', link: '/guide/getting-started'},
  {text: 'Prompt library', link: '/guide/library'},
  {text: 'Generating images', link: '/guide/generate'},
  {text: 'Gallery and review', link: '/guide/gallery'},
  {text: 'LoRA training', link: '/guide/lora'},
  {text: 'Image tools', link: '/guide/tools'},
  {text: 'Lab', link: '/guide/lab'},
  {text: 'Settings', link: '/guide/settings'},
  {text: 'Troubleshooting', link: '/guide/troubleshooting'},
];
const koGuide = [
  {text: '시작하기', link: '/ko/guide/getting-started'},
  {text: '프롬프트 라이브러리', link: '/ko/guide/library'},
  {text: '이미지 생성', link: '/ko/guide/generate'},
  {text: '갤러리와 검수', link: '/ko/guide/gallery'},
  {text: 'LoRA 학습', link: '/ko/guide/lora'},
  {text: '이미지 도구', link: '/ko/guide/tools'},
  {text: '실험실', link: '/ko/guide/lab'},
  {text: '설정', link: '/ko/guide/settings'},
  {text: '문제 해결', link: '/ko/guide/troubleshooting'},
];

export default defineConfig({
  title: 'Asset Studio',
  description: 'Local ComfyUI workspace for character image assets',
  base: '/asset-studio/',
  cleanUrls: true,
  lastUpdated: false,
  themeConfig: {
    search: {
      provider: 'local',
      options: {
        locales: {
          ko: {
            translations: {
              button: {buttonText: '검색', buttonAriaLabel: '검색'},
              modal: {
                noResultsText: '결과 없음',
                resetButtonTitle: '지우기',
                footer: {selectText: '선택', navigateText: '이동', closeText: '닫기'},
              },
            },
          },
        },
      },
    },
    socialLinks: [{icon: 'github', link: 'https://github.com/kiritype/asset-studio'}],
  },
  locales: {
    root: {
      label: 'English',
      lang: 'en',
      themeConfig: {
        nav: [{text: 'Guide', link: '/guide/getting-started'}],
        sidebar: {'/guide/': [{text: 'Guide', items: enGuide}]},
      },
    },
    ko: {
      label: '한국어',
      lang: 'ko',
      description: '캐릭터 이미지 에셋을 위한 로컬 ComfyUI 작업 공간',
      themeConfig: {
        nav: [{text: '가이드', link: '/ko/guide/getting-started'}],
        sidebar: {'/ko/': [{text: '가이드', items: koGuide}]},
        outline: {label: '이 페이지'},
        docFooter: {prev: '이전', next: '다음'},
        darkModeSwitchLabel: '테마',
        sidebarMenuLabel: '메뉴',
        returnToTopLabel: '맨 위로',
        langMenuLabel: '언어',
      },
    },
    ja: {label: '日本語', lang: 'ja'},
    'zh-CN': {label: '简体中文', lang: 'zh-CN'},
  },
});
