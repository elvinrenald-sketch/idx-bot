// ===== NAVBAR =====
const navbar = document.querySelector('.navbar');
const hamburger = document.querySelector('.hamburger');
const navLinks = document.querySelector('.nav-links');

window.addEventListener('scroll', () => {
  navbar.classList.toggle('scrolled', window.scrollY > 50);
});
hamburger.addEventListener('click', () => {
  hamburger.classList.toggle('active');
  navLinks.classList.toggle('open');
});
navLinks.querySelectorAll('a').forEach(a => a.addEventListener('click', () => {
  hamburger.classList.remove('active');
  navLinks.classList.remove('open');
}));

// ===== FADE IN =====
const obs = new IntersectionObserver((entries) => {
  entries.forEach(e => { if (e.isIntersecting) { e.target.classList.add('visible'); obs.unobserve(e.target); } });
}, { threshold: 0.1 });
document.querySelectorAll('.fade-in').forEach(el => obs.observe(el));

// ===== BMI CALCULATOR =====
function hitungBMI() {
  const berat = parseFloat(document.getElementById('bmi-berat').value);
  const tinggi = parseFloat(document.getElementById('bmi-tinggi').value);
  const box = document.getElementById('bmi-result');
  if (!berat || !tinggi || berat <= 0 || tinggi <= 0) { alert('Masukkan data yang valid!'); return; }
  const t = tinggi / 100;
  const bmi = berat / (t * t);
  const val = bmi.toFixed(1);
  let cat, cls;
  if (bmi < 18.5) { cat = 'Berat Badan Kurang'; cls = 'warning'; }
  else if (bmi < 25) { cat = 'Berat Badan Normal'; cls = 'normal'; }
  else if (bmi < 30) { cat = 'Kelebihan Berat Badan'; cls = 'warning'; }
  else { cat = 'Obesitas'; cls = 'danger'; }
  box.innerHTML = `<div class="result-value">${val}</div><div class="result-label">Indeks Massa Tubuh (BMI)</div><span class="result-category ${cls}">${cat}</span>
    <div class="result-details"><div class="result-detail-item"><span>Berat Badan</span><span>${berat} kg</span></div><div class="result-detail-item"><span>Tinggi Badan</span><span>${tinggi} cm</span></div><div class="result-detail-item"><span>Range Normal</span><span>18.5 - 24.9</span></div></div>`;
  box.classList.add('show');
}

// ===== CALORIE CALCULATOR =====
function hitungKalori() {
  const b = parseFloat(document.getElementById('kal-berat').value);
  const t = parseFloat(document.getElementById('kal-tinggi').value);
  const u = parseFloat(document.getElementById('kal-umur').value);
  const g = document.getElementById('kal-gender').value;
  const a = parseFloat(document.getElementById('kal-aktivitas').value);
  const box = document.getElementById('kalori-result');
  if (!b || !t || !u || !g || !a) { alert('Lengkapi semua data!'); return; }
  let bmr = g === 'pria' ? 88.362 + (13.397*b) + (4.799*t) - (5.677*u) : 447.593 + (9.247*b) + (3.098*t) - (4.330*u);
  const tdee = Math.round(bmr * a);
  bmr = Math.round(bmr);
  box.innerHTML = `<div class="result-value">${tdee}</div><div class="result-label">Kalori Harian (TDEE)</div><span class="result-category normal">kkal / hari</span>
    <div class="result-details"><div class="result-detail-item"><span>BMR (Metabolisme Basal)</span><span>${bmr} kkal</span></div><div class="result-detail-item"><span>Untuk Turun BB</span><span>${tdee - 500} kkal</span></div><div class="result-detail-item"><span>Untuk Naik BB</span><span>${tdee + 500} kkal</span></div></div>`;
  box.classList.add('show');
}

// ===== GENERATOR =====
let currentStep = 1;
let selections = { tujuan: '', tingkat: '', hari: 0 };

function selectOption(step, value) {
  const container = document.getElementById('step-' + step);
  container.querySelectorAll('.option-card').forEach(c => c.classList.remove('selected'));
  event.currentTarget.classList.add('selected');
  if (step === 1) selections.tujuan = value;
  else if (step === 2) selections.tingkat = value;
  else if (step === 3) selections.hari = parseInt(value);
}

function nextStep() {
  if (currentStep === 1 && !selections.tujuan) { alert('Pilih tujuan latihan!'); return; }
  if (currentStep === 2 && !selections.tingkat) { alert('Pilih tingkat keahlian!'); return; }
  if (currentStep === 3 && !selections.hari) { alert('Pilih jumlah hari!'); return; }
  if (currentStep === 3) { generateSchedule(); return; }
  document.getElementById('step-' + currentStep).classList.remove('active');
  currentStep++;
  document.getElementById('step-' + currentStep).classList.add('active');
  updateDots();
}

function prevStep() {
  if (currentStep <= 1) return;
  document.getElementById('step-' + currentStep).classList.remove('active');
  currentStep--;
  document.getElementById('step-' + currentStep).classList.add('active');
  updateDots();
}

function updateDots() {
  document.querySelectorAll('.step-dot').forEach((d, i) => {
    d.classList.remove('active', 'done');
    if (i + 1 === currentStep) d.classList.add('active');
    else if (i + 1 < currentStep) d.classList.add('done');
  });
  document.querySelectorAll('.step-line').forEach((l, i) => {
    l.classList.toggle('active', i + 1 < currentStep);
  });
}

// ===== EXERCISE DATABASE =====
const DB = {
  'turun-bb': {
    pemula: {
      dada: ['Push Up|3x12', 'Dumbbell Press|3x10', 'Chest Fly|3x12'],
      punggung: ['Lat Pulldown|3x12', 'Seated Row|3x10', 'Dumbbell Row|3x10'],
      kaki: ['Squat|3x15', 'Lunges|3x12', 'Leg Press|3x12'],
      bahu: ['Shoulder Press|3x12', 'Lateral Raise|3x15', 'Front Raise|3x12'],
      lengan: ['Bicep Curl|3x12', 'Tricep Pushdown|3x12', 'Hammer Curl|3x10'],
      core: ['Plank|3x30dtk', 'Crunch|3x20', 'Mountain Climber|3x15'],
      kardio: ['Treadmill|20 mnt', 'Jumping Jack|3x30', 'Burpee|3x10']
    },
    menengah: {
      dada: ['Bench Press|4x10', 'Incline Dumbbell Press|4x10', 'Cable Crossover|3x12'],
      punggung: ['Pull Up|4x8', 'Barbell Row|4x10', 'T-Bar Row|3x10'],
      kaki: ['Barbell Squat|4x10', 'Romanian Deadlift|4x10', 'Leg Curl|3x12'],
      bahu: ['Military Press|4x10', 'Arnold Press|3x10', 'Face Pull|3x15'],
      lengan: ['Barbell Curl|4x10', 'Skull Crusher|4x10', 'Preacher Curl|3x12'],
      core: ['Hanging Leg Raise|3x12', 'Cable Crunch|3x15', 'Ab Wheel|3x10'],
      kardio: ['HIIT Sprint|15 mnt', 'Box Jump|4x10', 'Battle Rope|3x30dtk']
    }
  },
  'bulking': {
    pemula: {
      dada: ['Bench Press|3x10', 'Incline DB Press|3x10', 'Push Up|3x15'],
      punggung: ['Lat Pulldown|3x10', 'Cable Row|3x10', 'Dumbbell Row|3x10'],
      kaki: ['Leg Press|3x12', 'Goblet Squat|3x12', 'Leg Extension|3x12'],
      bahu: ['DB Shoulder Press|3x10', 'Lateral Raise|3x15', 'Rear Delt Fly|3x12'],
      lengan: ['EZ Bar Curl|3x10', 'Tricep Dip|3x10', 'Concentration Curl|3x12'],
      core: ['Plank|3x45dtk', 'Russian Twist|3x20', 'Leg Raise|3x12']
    },
    menengah: {
      dada: ['Barbell Bench|5x5', 'Incline Bench|4x8', 'Weighted Dip|4x8'],
      punggung: ['Deadlift|5x5', 'Weighted Pull Up|4x8', 'Pendlay Row|4x8'],
      kaki: ['Back Squat|5x5', 'Front Squat|4x8', 'Hack Squat|3x10'],
      bahu: ['OHP|5x5', 'DB Lateral Raise|4x12', 'Upright Row|3x10'],
      lengan: ['Barbell Curl|4x8', 'Close Grip Bench|4x8', 'Incline DB Curl|3x10'],
      core: ['Weighted Plank|3x45dtk', 'Cable Woodchop|3x12', 'Dragon Flag|3x8']
    }
  },
  'kebugaran': {
    pemula: {
      dada: ['Push Up|3x12', 'DB Bench Press|3x10', 'Chest Fly Machine|3x12'],
      punggung: ['Assisted Pull Up|3x10', 'Cable Row|3x12', 'Lat Pulldown|3x10'],
      kaki: ['Bodyweight Squat|3x15', 'Walking Lunges|3x12', 'Calf Raise|3x15'],
      bahu: ['DB Press|3x10', 'Band Pull Apart|3x15', 'Lateral Raise|3x12'],
      lengan: ['DB Curl|3x12', 'Tricep Kickback|3x12', 'Wrist Curl|3x15'],
      core: ['Dead Bug|3x10', 'Bird Dog|3x10', 'Side Plank|3x20dtk'],
      kardio: ['Jalan Cepat|20 mnt', 'Sepeda Statis|15 mnt', 'Rowing|10 mnt']
    },
    menengah: {
      dada: ['Bench Press|4x8', 'DB Fly|3x12', 'Dip|3x10'],
      punggung: ['Pull Up|4x8', 'Barbell Row|4x8', 'Face Pull|3x15'],
      kaki: ['Squat|4x10', 'Deadlift|4x8', 'Bulgarian Split Squat|3x10'],
      bahu: ['Military Press|4x8', 'Arnold Press|3x10', 'Lateral Raise|4x12'],
      lengan: ['Barbell Curl|3x10', 'Overhead Extension|3x10', 'Chin Up|3x8'],
      core: ['Hanging Knee Raise|3x12', 'Pallof Press|3x10', 'Plank Walk|3x10'],
      kardio: ['Lari Interval|20 mnt', 'Jump Rope|10 mnt', 'Rowing|15 mnt']
    }
  }
};

const schedules = {
  3: [
    { day: 'Senin', focus: 'Dada & Trisep', groups: ['dada', 'lengan', 'core'] },
    { day: 'Selasa', rest: true },
    { day: 'Rabu', focus: 'Punggung & Bisep', groups: ['punggung', 'lengan', 'kardio'] },
    { day: 'Kamis', rest: true },
    { day: "Jum'at", focus: 'Kaki & Bahu', groups: ['kaki', 'bahu', 'core'] },
    { day: 'Sabtu', rest: true },
    { day: 'Minggu', rest: true }
  ],
  4: [
    { day: 'Senin', focus: 'Dada', groups: ['dada', 'core'] },
    { day: 'Selasa', focus: 'Punggung', groups: ['punggung', 'kardio'] },
    { day: 'Rabu', rest: true },
    { day: 'Kamis', focus: 'Bahu & Lengan', groups: ['bahu', 'lengan'] },
    { day: "Jum'at", focus: 'Kaki', groups: ['kaki', 'core'] },
    { day: 'Sabtu', rest: true },
    { day: 'Minggu', rest: true }
  ],
  5: [
    { day: 'Senin', focus: 'Dada', groups: ['dada', 'core'] },
    { day: 'Selasa', focus: 'Punggung', groups: ['punggung'] },
    { day: 'Rabu', focus: 'Bahu', groups: ['bahu', 'kardio'] },
    { day: 'Kamis', focus: 'Kaki', groups: ['kaki', 'core'] },
    { day: "Jum'at", focus: 'Lengan & Kardio', groups: ['lengan', 'kardio'] },
    { day: 'Sabtu', rest: true },
    { day: 'Minggu', rest: true }
  ]
};

function generateSchedule() {
  const { tujuan, tingkat, hari } = selections;
  const exercises = DB[tujuan]?.[tingkat];
  const sched = schedules[hari];
  if (!exercises || !sched) { alert('Kombinasi tidak tersedia!'); return; }
  const container = document.getElementById('schedule-result');
  const grid = document.getElementById('schedule-grid');
  const tujuanMap = { 'turun-bb': 'Turun Berat Badan', 'bulking': 'Bulking / Massa Otot', 'kebugaran': 'Jaga Kebugaran' };
  document.getElementById('sched-goal').textContent = tujuanMap[tujuan];
  document.getElementById('sched-level').textContent = tingkat.charAt(0).toUpperCase() + tingkat.slice(1);
  document.getElementById('sched-days').textContent = hari + ' Hari/Minggu';

  let html = '';
  sched.forEach(d => {
    if (d.rest) {
      html += `<div class="day-card rest"><div class="rest-text"><span>😴</span>Istirahat & Pemulihan</div></div>`;
    } else {
      let items = '';
      d.groups.forEach(g => {
        const arr = exercises[g];
        if (arr) {
          const ex = arr[Math.floor(Math.random() * arr.length)];
          const [name, sets] = ex.split('|');
          items += `<li class="exercise-item"><span>${name}</span><span class="sets">${sets}</span></li>`;
        }
      });
      html += `<div class="day-card"><div class="day-name">${d.day}</div><div class="day-focus">${d.focus}</div><ul class="exercise-list">${items}</ul></div>`;
    }
  });
  grid.innerHTML = html;
  container.classList.add('show');
  container.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function resetGenerator() {
  currentStep = 1;
  selections = { tujuan: '', tingkat: '', hari: 0 };
  document.querySelectorAll('.step-content').forEach(s => s.classList.remove('active'));
  document.getElementById('step-1').classList.add('active');
  document.querySelectorAll('.option-card').forEach(c => c.classList.remove('selected'));
  document.getElementById('schedule-result').classList.remove('show');
  updateDots();
}
