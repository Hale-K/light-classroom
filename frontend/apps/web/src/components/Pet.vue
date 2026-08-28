<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { useThemeStore } from '@/stores/theme'
import catHappy from '@/assets/pet/cat-happy.png'
import catExcited from '@/assets/pet/cat-excited.png'
import catSleeping from '@/assets/pet/cat-sleeping.png'
import catJump from '@/assets/pet/cat-jump.png'
import catPlay from '@/assets/pet/cat-play.png'
import catRun from '@/assets/pet/cat-run.png'

const themeStore = useThemeStore()

// ========== 状态机 ==========
type PetState =
  | 'idle' | 'walk' | 'run' | 'jump' | 'play' | 'sleep' | 'eat'
  | 'excited' | 'thinking' | 'loading' | 'wave' | 'cheer' | 'sad'
const state = ref<PetState>('idle')
const facing = ref<'left' | 'right'>('right')
const isHovering = ref(false)
const isMinimized = ref(false)
const isDragging = ref(false)
const isEntered = ref(false) // 入场动画

const stateLabel = computed(() => ({
  idle: '发呆中', walk: '散步中', run: '奔跑中', jump: '蹦跳中',
  play: '玩球中', sleep: '睡觉中', eat: '吃东西', excited: '超开心',
  thinking: '思考中', loading: '等待中', wave: '打招呼', cheer: '欢呼中', sad: '难过中',
}[state.value]))

const petImage = computed(() => ({
  idle: catHappy, walk: catHappy, run: catRun, jump: catJump,
  play: catPlay, sleep: catSleeping, eat: catHappy, excited: catExcited,
  thinking: catHappy, loading: catHappy, wave: catExcited, cheer: catJump, sad: catSleeping,
}[state.value]))

// ========== 位置 ==========
const offsetX = ref(0)
const offsetY = ref(0)
const MOVE_RANGE = 50

// ========== 对话 ==========
const dialogueMap: Record<PetState, string[]> = {
  idle: ['今天也要加油哦~', '老师在忙什么呢？', '小智陪着你~', '有点无聊呢...'],
  walk: ['溜达溜达~', '这里看看那里看看', '散步有益健康！'],
  run: ['冲冲冲！', '我最快！', '抓不到我吧~'],
  jump: ['耶！', '蹦高高！', '看我跳得高不高！'],
  play: ['这个球好好玩~', '再来一次！', '抓到你啦！'],
  sleep: ['嘘...zzZ', '好困哦...', '让我睡一会儿~'],
  eat: ['好吃！', '吧唧吧唧~', '谢谢老师！'],
  excited: ['好开心！', '最喜欢老师了！', '哇啊啊啊！'],
  thinking: ['让我想想...', '嗯...这个问题...', '正在动脑筋~'],
  loading: ['稍等一下哦~', '加载中...', '马上就好！'],
  wave: ['老师好呀！', '欢迎回来~', '嗨！'],
  cheer: ['太棒了！', '成功啦！', '老师真厉害！'],
  sad: ['别难过...', '会好起来的~', '小智陪着你'],
}
const animeLines = ['燃烧吧！', '上吧！', '我们能行！', '这就是青春！']
const matureLines = ['甚好。', '不急不躁。', '继续努力。', '辛苦了。']

const currentDialogue = ref('')
const showBubble = ref(false)
let bubbleTimer: ReturnType<typeof setTimeout> | null = null

function speak(text?: string) {
  let pool = dialogueMap[state.value] || dialogueMap.idle
  if (themeStore.current === 'anime' && !['sleep','eat','sad'].includes(state.value)) pool = animeLines
  if (themeStore.current === 'mature' && !['sleep','eat','sad'].includes(state.value)) pool = matureLines
  currentDialogue.value = text || pool[Math.floor(Math.random() * pool.length)]
  showBubble.value = true
  if (bubbleTimer) clearTimeout(bubbleTimer)
  bubbleTimer = setTimeout(() => { showBubble.value = false }, 3000)
}

// ========== 状态切换 ==========
let stateTimer: ReturnType<typeof setTimeout> | null = null
function setState(newState: PetState, duration?: number) {
  if (stateTimer) { clearTimeout(stateTimer); stateTimer = null }
  state.value = newState
  if (duration && newState !== 'sleep') {
    stateTimer = setTimeout(() => {
      if (state.value === newState) state.value = 'idle'
    }, duration)
  }
}

// ========== 全局事件 API ==========
// 其他组件可通过 window.dispatchEvent(new CustomEvent('pet:act', { detail: { action, text } })) 触发
type PetAction = 'thinking' | 'loading' | 'success' | 'error' | 'wave' | 'cheer' | 'sad' | 'idle' | 'say'
function onPetAct(e: Event) {
  const detail = (e as CustomEvent).detail as { action?: PetAction; text?: string; duration?: number }
  if (!detail?.action) return
  const map: Record<string, PetState> = {
    thinking: 'thinking', loading: 'loading', success: 'cheer',
    error: 'sad', wave: 'wave', cheer: 'cheer', sad: 'sad', idle: 'idle',
  }
  if (detail.action === 'say') {
    speak(detail.text)
    return
  }
  const target = map[detail.action]
  if (target) {
    setState(target, detail.duration || (detail.action === 'loading' ? 999999 : 2500))
    if (detail.text) speak(detail.text)
    else speak()
  }
}

// ========== 自主行为 ==========
let behaviorTimer: ReturnType<typeof setInterval> | null = null
let rafId: number | null = null
let walkTarget = 0
let walkSpeed = 0

const activeStates: PetState[] = ['walk', 'run', 'jump', 'play', 'idle']
function isActive() {
  return activeStates.includes(state.value) && !isHovering.value && !isDragging.value
}

function decideBehavior() {
  if (!isActive() || state.value === 'sleep') return
  const hour = new Date().getHours()
  if (hour >= 23 || hour < 6) { setState('sleep'); return }
  const r = Math.random()
  if (r < 0.22) {
    setState('walk'); walkTarget = (Math.random() - 0.5) * MOVE_RANGE * 2
    walkSpeed = 0.5 + Math.random() * 0.5
    facing.value = walkTarget > offsetX.value ? 'right' : 'left'
    setTimeout(() => { if (state.value === 'walk') setState('idle') }, 3000 + Math.random() * 2000)
  } else if (r < 0.38) {
    setState('run'); walkTarget = (Math.random() - 0.5) * MOVE_RANGE * 2
    walkSpeed = 1.5 + Math.random()
    facing.value = walkTarget > offsetX.value ? 'right' : 'left'
    setTimeout(() => { if (state.value === 'run') setState('idle') }, 1500 + Math.random() * 1000)
  } else if (r < 0.52) {
    setState('jump', 1200 + Math.random() * 800)
  } else if (r < 0.68) {
    setState('play', 2000 + Math.random() * 1500)
  } else {
    setState('idle')
    if (Math.random() < 0.3) speak()
  }
}

function animate() {
  if (state.value === 'walk' || state.value === 'run') {
    const dx = walkTarget - offsetX.value
    if (Math.abs(dx) > 1) offsetX.value += Math.sign(dx) * Math.min(Math.abs(dx), walkSpeed)
  } else if (['idle','excited','eat','thinking','loading','wave','cheer','sad'].includes(state.value)) {
    offsetX.value += (0 - offsetX.value) * 0.05
  }
  if (state.value === 'jump' || state.value === 'cheer') {
    const t = (Date.now() % 800) / 800
    offsetY.value = -Math.sin(t * Math.PI) * 20
  } else {
    offsetY.value += (0 - offsetY.value) * 0.15
  }
  rafId = requestAnimationFrame(animate)
}

function startBehaviorLoop() {
  behaviorTimer = setInterval(decideBehavior, 4000 + Math.random() * 3000)
  rafId = requestAnimationFrame(animate)
}

// ========== 互动 ==========
const petCount = ref(0)
const feedCount = ref(0)

function onClick() {
  if (state.value === 'sleep') { speak('嘘...别吵我睡觉~'); return }
  petCount.value++
  if (petCount.value % 5 === 0) { setState('excited', 2500); speak('最喜欢老师了！') }
  else if (petCount.value % 3 === 0) { setState('jump', 1500); speak('好舒服~') }
  else { setState('excited', 1500); speak() }
}

function onDoubleClick() {
  if (state.value === 'sleep') { setState('idle'); speak('啊...醒了醒了'); return }
  feedCount.value++
  setState('eat', 2000)
  speak(feedCount.value % 3 === 0 ? '吃太饱了~' : '好吃！谢谢老师！')
}

function onEnter() {
  isHovering.value = true
  if (state.value !== 'sleep' && !['thinking','loading'].includes(state.value)) {
    setState('play', 999999)
    speak('逗猫草！我来抓！')
  }
}
function onLeave() {
  isHovering.value = false
  if (state.value === 'play') setState('idle')
}
function onMouseMove(e: MouseEvent) {
  if (state.value === 'sleep' || isDragging.value) return
  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
  facing.value = e.clientX > rect.left + rect.width / 2 ? 'right' : 'left'
}

// ========== 时间驱动 ==========
let timeTimer: ReturnType<typeof setInterval> | null = null
function checkSleepTime() {
  const hour = new Date().getHours()
  if ((hour >= 23 || hour < 6) && state.value !== 'sleep') setState('sleep')
}

onMounted(() => {
  checkSleepTime()
  timeTimer = setInterval(checkSleepTime, 60000)
  startBehaviorLoop()
  window.addEventListener('pet:act', onPetAct as EventListener)
  // 入场动画
  setTimeout(() => { isEntered.value = true }, 100)
  setTimeout(() => {
    setState('wave', 2500)
    speak('老师好呀~我是小智！')
  }, 500)
})
onBeforeUnmount(() => {
  if (timeTimer) clearInterval(timeTimer)
  if (behaviorTimer) clearInterval(behaviorTimer)
  if (rafId) cancelAnimationFrame(rafId)
  if (bubbleTimer) clearTimeout(bubbleTimer)
  if (stateTimer) clearTimeout(stateTimer)
  window.removeEventListener('pet:act', onPetAct as EventListener)
})

const petName = computed(() => {
  if (themeStore.current === 'anime') return '热血小智'
  if (themeStore.current === 'mature') return '智先生'
  if (themeStore.current === 'cute') return '小智喵'
  return '小智'
})

function toggleMinimize() { isMinimized.value = !isMinimized.value }

defineExpose({ setDragging: (v: boolean) => { isDragging.value = v } })
</script>

<template>
  <div
    class="pet-wrap"
    :class="{ minimized: isMinimized, dragging: isDragging, entered: isEntered }"
    @mouseenter="onEnter"
    @mouseleave="onLeave"
    @mousemove="onMouseMove"
  >
    <template v-if="!isMinimized">
      <button class="pet-min-btn" @click.stop="toggleMinimize" title="收起">_</button>

      <!-- 对话气泡 -->
      <Transition name="bubble">
        <div v-if="showBubble" class="pet-bubble">{{ currentDialogue }}</div>
      </Transition>

      <!-- 逗猫草 -->
      <Transition name="teaser">
        <div v-if="isHovering && state !== 'sleep'" class="cat-teaser">
          <span class="teaser-stick" />
          <span class="teaser-feather">🪶</span>
        </div>
      </Transition>

      <!-- 思考气泡 -->
      <Transition name="bubble">
        <div v-if="state === 'thinking'" class="pet-think">💭</div>
      </Transition>
      <!-- 加载转圈 -->
      <Transition name="bubble">
        <div v-if="state === 'loading'" class="pet-loading">⚡</div>
      </Transition>

      <!-- 宠物（无背景板 + 脚下阴影） -->
      <div
        class="pet-stage"
        :class="[state, { 'face-left': facing === 'left' }]"
        :style="{ transform: `translate(${offsetX}px, ${offsetY}px)` }"
        @click="onClick"
        @dblclick="onDoubleClick"
      >
        <img :src="petImage" :alt="petName" class="pet-img" />
        <!-- 脚下阴影 -->
        <span class="pet-shadow" />
        <!-- 装饰 -->
        <span v-if="themeStore.current === 'cute'" class="deco heart">♡</span>
        <span v-if="themeStore.current === 'anime'" class="deco fire">🔥</span>
        <span v-if="state === 'play'" class="deco ball">⚽</span>
        <span v-if="state === 'eat'" class="deco food">🐟</span>
        <span v-if="state === 'sleep'" class="deco zzz">💤</span>
        <span v-if="state === 'wave'" class="deco wave">👋</span>
        <span v-if="state === 'cheer'" class="deco star">✨</span>
        <span v-if="state === 'sad'" class="deco tear">💧</span>
      </div>

      <!-- 信息条 -->
      <div class="pet-bar">
        <span class="pet-name">{{ petName }}</span>
        <span class="pet-state">
          <span class="state-dot" :class="state" />
          {{ stateLabel }}
        </span>
      </div>
    </template>

    <template v-else>
      <div class="pet-mini" @click="toggleMinimize" title="展开小智">
        <img :src="catHappy" :alt="petName" />
      </div>
    </template>
  </div>
</template>

<style scoped>
.pet-wrap {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  user-select: none;
  position: relative;
  opacity: 0;
  transform: translateY(20px);
  transition: opacity 0.5s ease, transform 0.5s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.pet-wrap.entered {
  opacity: 1;
  transform: translateY(0);
}
.pet-wrap.dragging { pointer-events: none; }

.pet-min-btn {
  position: absolute;
  top: 0; right: 4px;
  width: 20px; height: 20px;
  border-radius: 50%;
  border: 1px solid var(--line);
  background: var(--surface-1);
  color: var(--ink-500);
  font-size: 10px;
  cursor: pointer;
  display: grid; place-items: center;
  box-shadow: var(--shadow-xs);
  z-index: 10; line-height: 1;
  transition: all 0.15s;
}
.pet-min-btn:hover { color: var(--primary); border-color: var(--primary); }

/* 对话气泡 */
.pet-bubble {
  position: absolute;
  bottom: 100%;
  left: 50%;
  transform: translateX(-50%);
  margin-bottom: 6px;
  background: var(--surface-1);
  color: var(--ink-950);
  padding: 7px 12px;
  border-radius: 12px;
  border: 1px solid var(--line);
  font-size: 11px;
  line-height: 1.4;
  white-space: nowrap;
  box-shadow: var(--shadow-md);
  z-index: 10;
}
.pet-bubble::after {
  content: '';
  position: absolute;
  bottom: -6px; left: 50%;
  transform: translateX(-50%);
  border-left: 6px solid transparent;
  border-right: 6px solid transparent;
  border-top: 6px solid var(--surface-1);
}
.bubble-enter-active, .bubble-leave-active { transition: opacity 0.2s, transform 0.2s; }
.bubble-enter-from, .bubble-leave-to { opacity: 0; transform: translateX(-50%) translateY(6px); }

/* 思考/加载标记 */
.pet-think, .pet-loading {
  position: absolute;
  top: -8px; right: 8px;
  font-size: 18px;
  z-index: 8;
  animation: floatDeco 1.5s ease-in-out infinite;
}
.pet-loading { animation: spin 1s linear infinite; }
@keyframes spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }

/* 逗猫草 */
.cat-teaser {
  position: absolute;
  top: -20px; right: -4px;
  width: 40px; height: 50px;
  z-index: 5; pointer-events: none;
}
.teaser-stick {
  position: absolute;
  bottom: 0; left: 50%;
  width: 3px; height: 35px;
  background: linear-gradient(to top, #8B4513, #D2691E);
  border-radius: 2px;
  transform: rotate(-30deg);
  transform-origin: bottom center;
}
.teaser-feather {
  position: absolute;
  top: 0; left: 50%;
  font-size: 16px;
  transform: translateX(-50%) rotate(-30deg);
  animation: wiggle 0.35s ease-in-out infinite alternate;
}
@keyframes wiggle {
  from { transform: translateX(-50%) rotate(-40deg); }
  to { transform: translateX(-50%) rotate(-20deg); }
}
.teaser-enter-active { animation: teaserIn 0.25s ease-out; }
.teaser-leave-active { animation: teaserOut 0.2s ease-in; }
@keyframes teaserIn { from { opacity: 0; transform: translateY(8px) scale(0.5); } to { opacity: 1; } }
@keyframes teaserOut { from { opacity: 1; } to { opacity: 0; transform: translateY(-8px) scale(0.5); } }

/* 宠物舞台 */
.pet-stage {
  position: relative;
  width: 100px; height: 100px;
  display: grid; place-items: center;
  cursor: pointer;
  transition: transform 0.08s linear;
}
.pet-stage:active { transform: scale(0.94) !important; }
.pet-img {
  width: 90px; height: 90px;
  object-fit: contain;
  mix-blend-mode: multiply;
  transition: filter 0.2s;
  position: relative; z-index: 2;
}
.pet-stage.face-left .pet-img { transform: scaleX(-1); }
.pet-stage:hover .pet-img { filter: brightness(1.05); }

/* 脚下阴影（椭圆，非背景板） */
.pet-shadow {
  position: absolute;
  bottom: 2px; left: 50%;
  transform: translateX(-50%);
  width: 60px; height: 10px;
  background: radial-gradient(ellipse, rgba(0,0,0,0.18) 0%, transparent 70%);
  border-radius: 50%;
  z-index: 1;
  transition: width 0.2s, opacity 0.2s;
}
.pet-stage.jump .pet-shadow,
.pet-stage.cheer .pet-shadow {
  width: 40px;
  opacity: 0.4;
}
.pet-stage.sleep .pet-shadow { opacity: 0.3; }

/* 状态动画 */
.pet-stage.idle .pet-img { animation: breathe 3.5s ease-in-out infinite; }
.pet-stage.excited .pet-img { animation: bounce 0.45s ease-in-out infinite; }
.pet-stage.sleep .pet-img { opacity: 0.8; animation: breathe 4.5s ease-in-out infinite; }
.pet-stage.walk .pet-img { animation: walkBob 0.5s ease-in-out infinite; }
.pet-stage.run .pet-img { animation: runBob 0.25s ease-in-out infinite; }
.pet-stage.play .pet-img { animation: playSway 0.5s ease-in-out infinite; }
.pet-stage.eat .pet-img { animation: eatMunch 0.4s ease-in-out infinite; }
.pet-stage.thinking .pet-img { animation: thinkTilt 2s ease-in-out infinite; }
.pet-stage.loading .pet-img { animation: loadingWiggle 0.6s ease-in-out infinite; }
.pet-stage.wave .pet-img { animation: waveHand 0.5s ease-in-out infinite; }
.pet-stage.cheer .pet-img { animation: cheerJump 0.5s ease-in-out infinite; }
.pet-stage.sad .pet-img { animation: sadDroop 3s ease-in-out infinite; }

@keyframes breathe { 0%,100% { transform: scale(1); } 50% { transform: scale(1.03); } }
@keyframes bounce { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-6px); } }
@keyframes walkBob { 0%,100% { transform: translateY(0) rotate(-1deg); } 50% { transform: translateY(-3px) rotate(1deg); } }
@keyframes runBob { 0%,100% { transform: translateY(0) rotate(-3deg); } 50% { transform: translateY(-5px) rotate(3deg); } }
@keyframes playSway { 0%,100% { transform: rotate(-4deg); } 50% { transform: rotate(4deg); } }
@keyframes eatMunch { 0%,100% { transform: scaleY(1); } 50% { transform: scaleY(0.92); } }
@keyframes thinkTilt { 0%,100% { transform: rotate(0); } 50% { transform: rotate(-5deg) translateY(-2px); } }
@keyframes loadingWiggle { 0%,100% { transform: rotate(-2deg); } 50% { transform: rotate(2deg); } }
@keyframes waveHand { 0%,100% { transform: rotate(-3deg); } 50% { transform: rotate(5deg) translateY(-3px); } }
@keyframes cheerJump { 0%,100% { transform: scale(1) rotate(0); } 25% { transform: scale(1.05) rotate(-3deg); } 75% { transform: scale(1.05) rotate(3deg); } }
@keyframes sadDroop { 0%,100% { transform: translateY(0) rotate(0); opacity: 0.9; } 50% { transform: translateY(2px) rotate(-2deg); opacity: 0.7; } }

/* 装饰 */
.deco {
  position: absolute;
  pointer-events: none;
  font-size: 14px;
  z-index: 3;
}
.deco.heart { top: 2px; right: 6px; color: #EC4899; animation: floatDeco 2s ease-in-out infinite; }
.deco.fire { top: 0; right: 4px; animation: floatDeco 1.2s ease-in-out infinite; }
.deco.ball { bottom: 4px; left: 0; animation: ballRoll 0.7s ease-in-out infinite; }
.deco.food { bottom: 8px; right: 0; animation: eatFloat 0.4s ease-in-out infinite alternate; }
.deco.zzz { top: -4px; right: 8px; font-size: 16px; animation: zzzFloat 2s ease-in-out infinite; }
.deco.wave { top: -2px; right: 2px; animation: waveDeco 0.5s ease-in-out infinite; }
.deco.star { top: -6px; left: 50%; transform: translateX(-50%); animation: starBurst 0.8s ease-in-out infinite; }
.deco.tear { bottom: 20px; right: 12px; animation: tearDrop 2s ease-in-out infinite; }
@keyframes floatDeco { 0%,100% { transform: translateY(0) rotate(-5deg); opacity: 0.8; } 50% { transform: translateY(-3px) rotate(5deg); opacity: 1; } }
@keyframes ballRoll { 0%,100% { transform: translateX(0) rotate(0); } 50% { transform: translateX(5px) rotate(180deg); } }
@keyframes eatFloat { from { transform: translateY(0); } to { transform: translateY(-3px); } }
@keyframes zzzFloat { 0% { transform: translateY(0) scale(0.8); opacity: 0; } 50% { opacity: 1; } 100% { transform: translateY(-12px) scale(1.2); opacity: 0; } }
@keyframes waveDeco { 0%,100% { transform: rotate(-15deg); } 50% { transform: rotate(15deg); } }
@keyframes starBurst { 0%,100% { transform: translateX(-50%) scale(0.8); opacity: 0.5; } 50% { transform: translateX(-50%) scale(1.3); opacity: 1; } }
@keyframes tearDrop { 0% { transform: translateY(0); opacity: 0; } 30% { opacity: 1; } 100% { transform: translateY(10px); opacity: 0; } }

/* 信息条 */
.pet-bar {
  margin-top: 4px;
  width: 100%;
  padding: 4px 8px;
  background: var(--surface-1);
  border: 1px solid var(--line);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  box-shadow: var(--shadow-xs);
}
.pet-name { font-size: 11px; font-weight: 600; color: var(--ink-950); }
.pet-state { display: flex; align-items: center; gap: 4px; font-size: 9px; color: var(--ink-400); }
.state-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--green-500); }
.state-dot.excited, .state-dot.jump, .state-dot.play, .state-dot.run, .state-dot.walk,
.state-dot.cheer, .state-dot.wave { background: var(--amber-500); animation: pulse 1s ease-in-out infinite; }
.state-dot.thinking, .state-dot.loading { background: var(--blue-500); animation: pulse 0.8s ease-in-out infinite; }
.state-dot.sleep { background: var(--ink-400); }
.state-dot.eat { background: var(--orange-500); }
.state-dot.sad { background: var(--blue-400); }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }

/* 最小化 */
.pet-mini {
  width: 44px; height: 44px;
  border-radius: 50%;
  background: var(--surface-1);
  border: 1px solid var(--line);
  box-shadow: var(--shadow-sm);
  display: grid; place-items: center;
  cursor: pointer;
  transition: transform 0.15s;
}
.pet-mini:hover { transform: scale(1.1); }
.pet-mini img {
  width: 36px; height: 36px;
  object-fit: contain;
  mix-blend-mode: multiply;
  border-radius: 50%;
}
</style>
