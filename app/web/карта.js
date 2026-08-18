'use strict';

/* Карта на полотні. Малює браузер, тому класифікацію можна крутити
   без жодного звернення до сервера. Координати приходять у метрах. */

class Карта {
  constructor(полотно) {
    this.полотно = полотно;
    this.ктх = полотно.getContext('2d');
    this.шари = [];                 // знизу вгору
    this.підкладка = null;          // {зображення, межі}
    this.вигляд = { x: 0, y: 0, масштаб: 1 };   // масштаб = пікселів на метр
    this.наведене = null;
    this._слухати();
    this.підігнати_розмір();
  }

  // ---------------------------------------------------------- перетворення

  доЕкрана(x, y) {
    return [
      (x - this.вигляд.x) * this.вигляд.масштаб + this.полотно.clientWidth / 2,
      (this.вигляд.y - y) * this.вигляд.масштаб + this.полотно.clientHeight / 2
    ];
  }

  доСвіту(px, py) {
    return [
      (px - this.полотно.clientWidth / 2) / this.вигляд.масштаб + this.вигляд.x,
      this.вигляд.y - (py - this.полотно.clientHeight / 2) / this.вигляд.масштаб
    ];
  }

  підігнати_розмір() {
    const щільність = window.devicePixelRatio || 1;
    const ш = this.полотно.clientWidth, в = this.полотно.clientHeight;
    this.полотно.width = Math.max(1, Math.round(ш * щільність));
    this.полотно.height = Math.max(1, Math.round(в * щільність));
    this.ктх.setTransform(щільність, 0, 0, щільність, 0, 0);
    this.малювати();
  }

  вписати(межі, запас = 0.06) {
    if (!межі) return;
    const [xmin, ymin, xmax, ymax] = межі;
    const ш = Math.max(xmax - xmin, 1), в = Math.max(ymax - ymin, 1);
    const пш = this.полотно.clientWidth || 800, пв = this.полотно.clientHeight || 600;
    this.вигляд.масштаб = Math.min(пш / ш, пв / в) * (1 - запас * 2);
    this.вигляд.x = (xmin + xmax) / 2;
    this.вигляд.y = (ymin + ymax) / 2;
    this.малювати();
  }

  спільні_межі() {
    let м = null;
    const врахувати = (інші) => {
      if (!інші) return;
      м = м ? [Math.min(м[0], інші[0]), Math.min(м[1], інші[1]),
               Math.max(м[2], інші[2]), Math.max(м[3], інші[3])] : інші.slice();
    };
    this.шари.forEach(ш => врахувати(ш.дані && ш.дані['межі']));
    if (this.підкладка) врахувати(this.підкладка.межі);
    return м;
  }

  // ---------------------------------------------------------------- шари

  покласти(шар) {
    const було = this.шари.findIndex(ш => ш.ключ === шар.ключ);
    if (було >= 0) this.шари[було] = шар; else this.шари.push(шар);
    this._класи(шар);
    this.малювати();
  }

  прибрати(ключ) {
    this.шари = this.шари.filter(ш => ш.ключ !== ключ);
    this.малювати();
  }

  знайти(ключ) { return this.шари.find(ш => ш.ключ === ключ); }

  _класи(шар) {
    const д = шар.дані;
    if (!д || !д['значення'] || !д['межі_класів'] || д['межі_класів'].length < 2) {
      шар._індекс = null;
      return;
    }
    const межі = д['межі_класів'], останній = межі.length - 2;
    шар._індекс = д['значення'].map(з => {
      if (з === null) return -1;
      let і = 0;
      while (і < останній && з > межі[і + 1]) і++;
      return і;
    });
  }

  перекласифікувати(ключ, межі, кольори) {
    const шар = this.знайти(ключ);
    if (!шар) return;
    шар.дані['межі_класів'] = межі;
    шар.дані['кольори'] = кольори;
    this._класи(шар);
    this.малювати();
  }

  // ------------------------------------------------------------ малювання

  малювати() {
    const ктх = this.ктх;
    const ш = this.полотно.clientWidth, в = this.полотно.clientHeight;
    ктх.clearRect(0, 0, ш, в);

    if (this.підкладка && this.підкладка.зображення) {
      const [xmin, ymin, xmax, ymax] = this.підкладка.межі;
      const [лx, лy] = this.доЕкрана(xmin, ymax);
      const [пx, пy] = this.доЕкрана(xmax, ymin);
      ктх.globalAlpha = this.підкладка.прозорість == null ? 1 : this.підкладка.прозорість;
      ктх.imageSmoothingEnabled = true;
      ктх.drawImage(this.підкладка.зображення, лx, лy, пx - лx, пy - лy);
      ктх.globalAlpha = 1;
    }

    for (const шар of this.шари) {
      if (!шар.видимий || !шар.дані) continue;
      ктх.globalAlpha = шар.прозорість == null ? 1 : шар.прозорість;
      if (шар.дані['вид'] === 'полігон') this._полігони(шар);
      else this._точки(шар);
      ктх.globalAlpha = 1;
    }

    this._масштабна_лінійка();
  }

  _колір(шар, і) {
    const кольори = шар.дані['кольори'];
    if (!шар._індекс || !кольори) return шар.колір || 'var(--акцент)';
    const к = шар._індекс[і];
    return к < 0 ? 'rgba(140,140,140,.5)' : кольори[Math.min(к, кольори.length - 1)];
  }

  _точки(шар) {
    const ктх = this.ктх;
    const коорд = шар.дані['коорд'];
    if (!коорд) return;
    const радіус = Math.max(1, Math.min(7, this.вигляд.масштаб * 1.1));
    const ш = this.полотно.clientWidth, в = this.полотно.clientHeight;

    // групуємо за класом, щоб не смикати fillStyle на кожній точці
    const кольори = шар.дані['кольори'] || [шар.колір || '#3e7a32'];
    const групи = new Map();
    for (let і = 0; і < коорд.length; і += 2) {
      const н = і / 2;
      const к = шар._індекс ? шар._індекс[н] : 0;
      if (!групи.has(к)) групи.set(к, []);
      групи.get(к).push(н);
    }

    for (const [к, номери] of групи) {
      ктх.fillStyle = к < 0 ? 'rgba(150,150,150,.45)'
                            : кольори[Math.min(к, кольори.length - 1)];
      ктх.beginPath();
      for (const н of номери) {
        const [px, py] = this.доЕкрана(коорд[н * 2], коорд[н * 2 + 1]);
        if (px < -20 || py < -20 || px > ш + 20 || py > в + 20) continue;
        ктх.moveTo(px + радіус, py);
        ктх.arc(px, py, радіус, 0, 6.2832);
      }
      ктх.fill();
    }
  }

  _полігони(шар) {
    const ктх = this.ктх;
    const фігури = шар.дані['фігури'] || [];
    фігури.forEach((кільця, і) => {
      ктх.beginPath();
      кільця.forEach(кільце => {
        for (let ј = 0; ј < кільце.length; ј += 2) {
          const [px, py] = this.доЕкрана(кільце[ј], кільце[ј + 1]);
          if (ј === 0) ктх.moveTo(px, py); else ктх.lineTo(px, py);
        }
        ктх.closePath();
      });
      if (шар.заливка !== false && шар.дані['значення']) {
        ктх.fillStyle = this._колір(шар, і);
        ктх.fill('evenodd');
      }
      ктх.lineWidth = шар.товщина || 2;
      ктх.strokeStyle = шар.обвід || 'rgba(30,77,43,.9)';
      ктх.stroke();
    });
  }

  _масштабна_лінійка() {
    const поле = document.getElementById('масштаб');
    if (!поле) return;
    const цільова = 110 / this.вигляд.масштаб;      // метрів на ~110 пікселів
    const крок = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000]
      .reduce((а, б) => Math.abs(б - цільова) < Math.abs(а - цільова) ? б : а);
    поле.style.width = Math.round(крок * this.вигляд.масштаб) + 'px';
    поле.textContent = крок >= 1000 ? (крок / 1000) + ' км' : крок + ' м';
  }

  // ------------------------------------------------------------- події

  _слухати() {
    const п = this.полотно;
    let тягну = false, звідкиX = 0, звідкиY = 0;

    п.addEventListener('mousedown', п2 => {
      тягну = true; звідкиX = п2.clientX; звідкиY = п2.clientY;
      п.style.cursor = 'grabbing';
    });
    window.addEventListener('mouseup', () => { тягну = false; п.style.cursor = 'grab'; });
    window.addEventListener('mousemove', п2 => {
      if (!тягну) return;
      this.вигляд.x -= (п2.clientX - звідкиX) / this.вигляд.масштаб;
      this.вигляд.y += (п2.clientY - звідкиY) / this.вигляд.масштаб;
      звідкиX = п2.clientX; звідкиY = п2.clientY;
      this.малювати();
    });

    п.addEventListener('wheel', п2 => {
      п2.preventDefault();
      const прям = п.getBoundingClientRect();
      const [дсX, дсY] = this.доСвіту(п2.clientX - прям.left, п2.clientY - прям.top);
      const крок = п2.deltaY < 0 ? 1.18 : 1 / 1.18;
      this.вигляд.масштаб = Math.max(0.02, Math.min(40, this.вигляд.масштаб * крок));
      const [післяX, післяY] = this.доСвіту(п2.clientX - прям.left, п2.clientY - прям.top);
      this.вигляд.x += дсX - післяX;
      this.вигляд.y += дсY - післяY;
      this.малювати();
    }, { passive: false });

    п.addEventListener('click', п2 => {
      const прям = п.getBoundingClientRect();
      const знахідка = this.влучити(п2.clientX - прям.left, п2.clientY - прям.top);
      if (this.наклацнуто) this.наклацнуто(знахідка);
    });

    window.addEventListener('resize', () => this.підігнати_розмір());
  }

  влучити(px, py, допуск = 9) {
    for (let і = this.шари.length - 1; і >= 0; і--) {
      const шар = this.шари[і];
      if (!шар.видимий || !шар.дані) continue;

      if (шар.дані['вид'] === 'полігон') {
        const [сx, сy] = this.доСвіту(px, py);
        const номер = this._полігон_під(шар, сx, сy);
        if (номер >= 0) {
          return { шар, номер, підпис: (шар.дані['підписи'] || [])[номер] || {} };
        }
        continue;
      }

      const коорд = шар.дані['коорд'];
      if (!коорд) continue;
      let найкращий = -1, найближче = допуск * допуск;
      for (let ј = 0; ј < коорд.length; ј += 2) {
        const [тx, тy] = this.доЕкрана(коорд[ј], коорд[ј + 1]);
        const д = (тx - px) * (тx - px) + (тy - py) * (тy - py);
        if (д < найближче) { найближче = д; найкращий = ј / 2; }
      }
      if (найкращий >= 0) {
        const підпис = {};
        if (шар.дані['атрибут'])
          підпис[шар.дані['атрибут']] = шар.дані['значення'][найкращий];
        const мітки = шар.дані['мітки'] || {};
        Object.keys(мітки).forEach(к => { підпис[к] = мітки[к][найкращий]; });
        return { шар, номер: найкращий, підпис };
      }
    }
    return null;
  }

  _полігон_під(шар, x, y) {
    const фігури = шар.дані['фігури'] || [];
    for (let і = 0; і < фігури.length; і++) {
      let всередині = false;
      for (const кільце of фігури[і]) {
        for (let ј = 0, к = кільце.length - 2; ј < кільце.length; к = ј, ј += 2) {
          const xi = кільце[ј], yi = кільце[ј + 1];
          const xj = кільце[к], yj = кільце[к + 1];
          if (((yi > y) !== (yj > y))
              && (x < (xj - xi) * (y - yi) / ((yj - yi) || 1e-9) + xi)) всередині = !всередині;
        }
      }
      if (всередині) return і;
    }
    return -1;
  }
}
