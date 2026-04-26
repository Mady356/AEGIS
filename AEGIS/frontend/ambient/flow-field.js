/* ============================================================
   AEGIS AMBIENT FLOW FIELD

   A continuous flowing background animation generated from
   3D simplex noise. Creates the impression of a living system
   computing in the background without competing with the
   cockpit's foreground elements.

   Self-contained — single canvas (#ambient-flow), single rAF
   loop, no external dependencies.
   ============================================================ */

(function () {
  'use strict';

  // Respect reduced-motion preference. The CSS already hides the
  // canvas; we just skip the heavy work entirely.
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    return;
  }

  // ============================================================
  // 3D SIMPLEX NOISE
  // Adapted from Stefan Gustavson's reference implementation.
  // Produces smooth pseudo-random scalar values across 3D space.
  // ============================================================
  const SimplexNoise = (function () {
    const F3 = 1.0 / 3.0;
    const G3 = 1.0 / 6.0;
    const grad3 = [
      [ 1, 1, 0], [-1, 1, 0], [ 1,-1, 0], [-1,-1, 0],
      [ 1, 0, 1], [-1, 0, 1], [ 1, 0,-1], [-1, 0,-1],
      [ 0, 1, 1], [ 0,-1, 1], [ 0, 1,-1], [ 0,-1,-1],
    ];

    function buildPermutationTable(seed) {
      const p = new Uint8Array(256);
      for (let i = 0; i < 256; i++) p[i] = i;
      let s = seed || 1;
      for (let i = 255; i > 0; i--) {
        s = (s * 9301 + 49297) % 233280;
        const n = Math.floor((s / 233280) * (i + 1));
        const q = p[i];
        p[i] = p[n];
        p[n] = q;
      }
      return p;
    }

    return function (seed) {
      const p = buildPermutationTable(seed);
      const perm = new Uint8Array(512);
      const permMod12 = new Uint8Array(512);
      for (let i = 0; i < 512; i++) {
        perm[i] = p[i & 255];
        permMod12[i] = perm[i] % 12;
      }

      this.noise3D = function (xin, yin, zin) {
        let n0 = 0, n1 = 0, n2 = 0, n3 = 0;
        const s = (xin + yin + zin) * F3;
        const i = Math.floor(xin + s);
        const j = Math.floor(yin + s);
        const k = Math.floor(zin + s);
        const t = (i + j + k) * G3;
        const X0 = i - t;
        const Y0 = j - t;
        const Z0 = k - t;
        const x0 = xin - X0;
        const y0 = yin - Y0;
        const z0 = zin - Z0;

        let i1, j1, k1;
        let i2, j2, k2;
        if (x0 >= y0) {
          if (y0 >= z0)        { i1=1; j1=0; k1=0; i2=1; j2=1; k2=0; }
          else if (x0 >= z0)   { i1=1; j1=0; k1=0; i2=1; j2=0; k2=1; }
          else                 { i1=0; j1=0; k1=1; i2=1; j2=0; k2=1; }
        } else {
          if (y0 < z0)         { i1=0; j1=0; k1=1; i2=0; j2=1; k2=1; }
          else if (x0 < z0)    { i1=0; j1=1; k1=0; i2=0; j2=1; k2=1; }
          else                 { i1=0; j1=1; k1=0; i2=1; j2=1; k2=0; }
        }

        const x1 = x0 - i1 + G3;
        const y1 = y0 - j1 + G3;
        const z1 = z0 - k1 + G3;
        const x2 = x0 - i2 + 2.0 * G3;
        const y2 = y0 - j2 + 2.0 * G3;
        const z2 = z0 - k2 + 2.0 * G3;
        const x3 = x0 - 1.0 + 3.0 * G3;
        const y3 = y0 - 1.0 + 3.0 * G3;
        const z3 = z0 - 1.0 + 3.0 * G3;

        const ii = i & 255;
        const jj = j & 255;
        const kk = k & 255;

        let t0 = 0.6 - x0*x0 - y0*y0 - z0*z0;
        if (t0 >= 0) {
          const gi0 = permMod12[ii + perm[jj + perm[kk]]];
          const g0 = grad3[gi0];
          t0 *= t0;
          n0 = t0 * t0 * (g0[0]*x0 + g0[1]*y0 + g0[2]*z0);
        }

        let t1 = 0.6 - x1*x1 - y1*y1 - z1*z1;
        if (t1 >= 0) {
          const gi1 = permMod12[ii+i1 + perm[jj+j1 + perm[kk+k1]]];
          const g1 = grad3[gi1];
          t1 *= t1;
          n1 = t1 * t1 * (g1[0]*x1 + g1[1]*y1 + g1[2]*z1);
        }

        let t2 = 0.6 - x2*x2 - y2*y2 - z2*z2;
        if (t2 >= 0) {
          const gi2 = permMod12[ii+i2 + perm[jj+j2 + perm[kk+k2]]];
          const g2 = grad3[gi2];
          t2 *= t2;
          n2 = t2 * t2 * (g2[0]*x2 + g2[1]*y2 + g2[2]*z2);
        }

        let t3 = 0.6 - x3*x3 - y3*y3 - z3*z3;
        if (t3 >= 0) {
          const gi3 = permMod12[ii+1 + perm[jj+1 + perm[kk+1]]];
          const g3 = grad3[gi3];
          t3 *= t3;
          n3 = t3 * t3 * (g3[0]*x3 + g3[1]*y3 + g3[2]*z3);
        }

        return 32.0 * (n0 + n1 + n2 + n3);
      };
    };
  })();

  // ============================================================
  // CONFIGURATION
  // ============================================================
  const CONFIG = {
    PARTICLE_COUNT:        280,
    PARTICLE_SPEED_MIN:    0.4,
    PARTICLE_SPEED_MAX:    0.8,
    PARTICLE_LIFETIME_MIN: 3000,    // ms
    PARTICLE_LIFETIME_MAX: 7000,    // ms
    PARTICLE_OPACITY_MIN:  0.06,
    PARTICLE_OPACITY_MAX:  0.14,
    TRAIL_LENGTH:          10,
    LINE_WIDTH:            0.8,
    NOISE_SCALE:           0.0015,  // Lower = larger flow patterns
    NOISE_TIME_SCALE:      0.0003,  // Flow field evolution rate per frame
    AMBER_RATIO_BASE:      0.25,    // Fraction of amber particles
    AMBER_PULSE_PEAK:      0.35,    // Peak during pulse
    AMBER_PULSE_INTERVAL:  8000,    // ms between pulses
    AMBER_PULSE_RAMP_UP:   1000,    // ms to peak
    AMBER_PULSE_RAMP_DOWN: 2000,    // ms back to base
    VELOCITY_LERP:         0.05,    // Smoothing factor toward flow direction
    FADE_IN_DURATION:      200,     // ms
    FADE_OUT_DURATION:     400,     // ms
    BG_FADE_ALPHA:         0.08,    // Per-frame canvas-clear alpha (motion blur)
  };

  const COLORS = {
    BONE:  { r: 232, g: 213, b: 183 },
    AMBER: { r: 217, g: 119, b: 6   },
  };

  // ============================================================
  // SETUP
  // ============================================================
  const canvas = document.getElementById('ambient-flow');
  if (!canvas) {
    console.warn('[ambient] #ambient-flow canvas not found');
    return;
  }

  const ctx = canvas.getContext('2d');
  const noise = new SimplexNoise(Date.now());

  let width = 0;
  let height = 0;
  let dpr = 1;
  let particles = [];
  let timeOffset = 0;
  let lastFrameTime = performance.now();
  let isPaused = false;
  let rafId = 0;

  function resizeCanvas() {
    dpr = window.devicePixelRatio || 1;
    width = window.innerWidth;
    height = window.innerHeight;
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';
    // Reset transform first (in case this is a re-resize) then scale
    // so all draw operations work in CSS pixels.
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.scale(dpr, dpr);
  }

  // ============================================================
  // PARTICLE SYSTEM
  // ============================================================
  function createParticle(forceAmber) {
    const lifetime = CONFIG.PARTICLE_LIFETIME_MIN +
      Math.random() * (CONFIG.PARTICLE_LIFETIME_MAX - CONFIG.PARTICLE_LIFETIME_MIN);
    const baseOpacity = CONFIG.PARTICLE_OPACITY_MIN +
      Math.random() * (CONFIG.PARTICLE_OPACITY_MAX - CONFIG.PARTICLE_OPACITY_MIN);

    return {
      x: Math.random() * width,
      y: Math.random() * height,
      vx: 0,
      vy: 0,
      speed: CONFIG.PARTICLE_SPEED_MIN +
        Math.random() * (CONFIG.PARTICLE_SPEED_MAX - CONFIG.PARTICLE_SPEED_MIN),
      isAmber: forceAmber !== undefined ? forceAmber
        : (Math.random() < currentAmberRatio()),
      baseOpacity: baseOpacity,
      lifetime: lifetime,
      birth: performance.now(),
      trail: [],
    };
  }

  function initParticles() {
    particles = new Array(CONFIG.PARTICLE_COUNT);
    for (let i = 0; i < CONFIG.PARTICLE_COUNT; i++) {
      const p = createParticle();
      // Stagger birth times so the field doesn't all spawn at once.
      p.birth = performance.now() - Math.random() * p.lifetime;
      particles[i] = p;
    }
  }

  // ============================================================
  // AMBER PULSE
  // Every AMBER_PULSE_INTERVAL ms, the amber proportion ramps up
  // for AMBER_PULSE_RAMP_UP ms then back down for _RAMP_DOWN ms.
  // ============================================================
  function currentAmberRatio() {
    const cycleTime = performance.now() % CONFIG.AMBER_PULSE_INTERVAL;

    if (cycleTime < CONFIG.AMBER_PULSE_RAMP_UP) {
      const t = cycleTime / CONFIG.AMBER_PULSE_RAMP_UP;
      return CONFIG.AMBER_RATIO_BASE +
        (CONFIG.AMBER_PULSE_PEAK - CONFIG.AMBER_RATIO_BASE) * t;
    }
    if (cycleTime < CONFIG.AMBER_PULSE_RAMP_UP + CONFIG.AMBER_PULSE_RAMP_DOWN) {
      const t = (cycleTime - CONFIG.AMBER_PULSE_RAMP_UP)
        / CONFIG.AMBER_PULSE_RAMP_DOWN;
      return CONFIG.AMBER_PULSE_PEAK +
        (CONFIG.AMBER_RATIO_BASE - CONFIG.AMBER_PULSE_PEAK) * t;
    }
    return CONFIG.AMBER_RATIO_BASE;
  }

  // ============================================================
  // FLOW FIELD
  // Each (x, y, t) → flow angle in [0, 2π].
  // ============================================================
  function getFlowAngle(x, y) {
    const n = noise.noise3D(
      x * CONFIG.NOISE_SCALE,
      y * CONFIG.NOISE_SCALE,
      timeOffset,
    );
    // Map [-1, 1] → [0, 2π]
    return (n + 1) * Math.PI;
  }

  // ============================================================
  // PARTICLE LIFECYCLE
  // ============================================================
  function getParticleOpacity(p) {
    const age = performance.now() - p.birth;
    if (age < CONFIG.FADE_IN_DURATION) {
      return p.baseOpacity * (age / CONFIG.FADE_IN_DURATION);
    }
    const lifeRemaining = p.lifetime - age;
    if (lifeRemaining < CONFIG.FADE_OUT_DURATION) {
      return p.baseOpacity * (lifeRemaining / CONFIG.FADE_OUT_DURATION);
    }
    return p.baseOpacity;
  }

  function isParticleDead(p) {
    return (performance.now() - p.birth) > p.lifetime
      || p.x < -50 || p.x > width + 50
      || p.y < -50 || p.y > height + 50;
  }

  function updateParticle(p, frameMultiplier) {
    const angle = getFlowAngle(p.x, p.y);
    const targetVx = Math.cos(angle) * p.speed;
    const targetVy = Math.sin(angle) * p.speed;

    // Smooth velocity toward the flow direction so abrupt changes
    // in the noise field curve the particle rather than snapping it.
    p.vx += (targetVx - p.vx) * CONFIG.VELOCITY_LERP;
    p.vy += (targetVy - p.vy) * CONFIG.VELOCITY_LERP;

    p.x += p.vx * frameMultiplier;
    p.y += p.vy * frameMultiplier;

    p.trail.push({ x: p.x, y: p.y });
    if (p.trail.length > CONFIG.TRAIL_LENGTH) {
      p.trail.shift();
    }
  }

  function respawnParticle(p) {
    Object.assign(p, createParticle());
  }

  // ============================================================
  // RENDERING
  // ============================================================
  function drawParticle(p) {
    if (p.trail.length < 2) return;
    const opacity = getParticleOpacity(p);
    if (opacity <= 0) return;

    const c = p.isAmber ? COLORS.AMBER : COLORS.BONE;

    // Draw trail as fading line segments. Older segments are dimmer.
    for (let i = 1; i < p.trail.length; i++) {
      const t = i / p.trail.length; // 0 = oldest, 1 = newest
      const segOpacity = opacity * t;
      ctx.strokeStyle = 'rgba(' + c.r + ',' + c.g + ',' + c.b + ',' + segOpacity + ')';
      ctx.beginPath();
      ctx.moveTo(p.trail[i - 1].x, p.trail[i - 1].y);
      ctx.lineTo(p.trail[i].x, p.trail[i].y);
      ctx.stroke();
    }
  }

  // ============================================================
  // MAIN LOOP
  // ============================================================
  function animate(now) {
    if (isPaused) {
      rafId = requestAnimationFrame(animate);
      return;
    }
    const deltaTime = now - lastFrameTime;
    lastFrameTime = now;

    // Per-frame partial clear: leaves a faint trail of recent draw
    // calls, which is what creates the visible streams without
    // tracking long trail buffers.
    ctx.fillStyle = 'rgba(10, 9, 7, ' + CONFIG.BG_FADE_ALPHA + ')';
    ctx.fillRect(0, 0, width, height);

    // Advance the flow field's time dimension. Scaled by the frame's
    // share of a 60fps tick so the flow evolves at a consistent
    // wall-clock rate even if the framerate drops.
    const frameMultiplier = deltaTime / (1000 / 60);
    timeOffset += CONFIG.NOISE_TIME_SCALE * frameMultiplier;

    ctx.lineWidth = CONFIG.LINE_WIDTH;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    for (let i = 0; i < particles.length; i++) {
      const p = particles[i];
      updateParticle(p, frameMultiplier);
      if (isParticleDead(p)) {
        respawnParticle(p);
      }
      drawParticle(p);
    }

    rafId = requestAnimationFrame(animate);
  }

  // ============================================================
  // LIFECYCLE
  // ============================================================
  function init() {
    resizeCanvas();
    initParticles();
    lastFrameTime = performance.now();
    rafId = requestAnimationFrame(animate);
  }

  // Resize handling — debounced so a window drag doesn't thrash.
  let resizeTimer = null;
  window.addEventListener('resize', function () {
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      resizeCanvas();
      // Particles keep their positions; the flow field adapts.
    }, 100);
  });

  // Pause when the tab is backgrounded — saves CPU/battery, and
  // resets lastFrameTime on resume so the deltaTime jump from the
  // pause doesn't catapult particles across the screen.
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) {
      isPaused = true;
    } else {
      isPaused = false;
      lastFrameTime = performance.now();
    }
  });

  // Boot
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
