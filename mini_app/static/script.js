// Initialize Telegram WebApp
const tg = window.Telegram.WebApp;
tg.expand();
tg.ready();

// Get DOM elements
const canvas = document.getElementById('roulette');
const ctx = canvas.getContext('2d');
const spinBtn = document.getElementById('spinBtn');
const resultDiv = document.getElementById('result');
const resultPrize = document.querySelector('.result-prize');
const alreadySpunDiv = document.getElementById('alreadySpun');
const alreadySpunPrize = document.querySelector('.already-spun-prize');
const loadingDiv = document.getElementById('loading');

// Configuration
const PRIZES = [5000, 10000, 15000, 20000, 25000, 30000];
const COLORS = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#FFA07A', '#98D8C8', '#F39C12'];
const CENTER_X = canvas.width / 2;
const CENTER_Y = canvas.height / 2;
const RADIUS = 150;

// State
let currentAngle = 0;
let isSpinning = false;
let animationId = null;

// Format prize
function formatPrize(amount) {
    return `${amount.toLocaleString('ru-RU')} ₽`;
}

// Draw the wheel
function drawWheel(rotation = 0) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    const segments = PRIZES.length;
    const arc = (2 * Math.PI) / segments;
    
    // Draw segments
    for (let i = 0; i < segments; i++) {
        const angle = rotation + i * arc;
        
        // Draw segment
        ctx.beginPath();
        ctx.fillStyle = COLORS[i];
        ctx.moveTo(CENTER_X, CENTER_Y);
        ctx.arc(CENTER_X, CENTER_Y, RADIUS, angle, angle + arc);
        ctx.lineTo(CENTER_X, CENTER_Y);
        ctx.fill();
        
        // Draw segment border
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.3)';
        ctx.lineWidth = 2;
        ctx.stroke();
        
        // Draw prize text
        ctx.save();
        ctx.translate(CENTER_X, CENTER_Y);
        ctx.rotate(angle + arc / 2);
        ctx.textAlign = 'center';
        ctx.fillStyle = 'white';
        ctx.font = 'bold 20px Arial';
        ctx.shadowColor = 'rgba(0, 0, 0, 0.5)';
        ctx.shadowBlur = 4;
        ctx.fillText(formatPrize(PRIZES[i]), RADIUS * 0.65, 8);
        ctx.restore();
    }
    
    // Draw center circle
    ctx.beginPath();
    ctx.arc(CENTER_X, CENTER_Y, 25, 0, 2 * Math.PI);
    ctx.fillStyle = 'white';
    ctx.fill();
    ctx.strokeStyle = '#667eea';
    ctx.lineWidth = 3;
    ctx.stroke();
}

// Animate spin
function animateSpin(targetPrize) {
    const targetIndex = PRIZES.indexOf(targetPrize);
    const arc = (2 * Math.PI) / PRIZES.length;
    
    // Calculate target angle (stop at top, accounting for pointer at 12 o'clock)
    // Pointer is at top (270 degrees or -PI/2), segments start from right (0 degrees)
    // We need to rotate so the CENTER of target segment is under the pointer
    const pointerAngle = -Math.PI / 2; // Top position (12 o'clock)
    const segmentStartAngle = targetIndex * arc;
    const segmentCenterAngle = segmentStartAngle + (arc / 2);
    const targetAngle = pointerAngle - segmentCenterAngle;
    
    // Normalize to positive angle and add full rotations
    const normalizedTargetAngle = (targetAngle % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI);
    const fullRotations = 5;
    const totalRotation = (fullRotations * 2 * Math.PI) + normalizedTargetAngle;
    
    const startTime = Date.now();
    const duration = 4000; // 4 seconds
    
    canvas.classList.add('spinning');
    
    function animate() {
        const elapsed = Date.now() - startTime;
        const progress = Math.min(elapsed / duration, 1);
        
        // Easing function (ease-out cubic)
        const easeProgress = 1 - Math.pow(1 - progress, 3);
        
        currentAngle = easeProgress * totalRotation;
        drawWheel(currentAngle);
        
        if (progress < 1) {
            animationId = requestAnimationFrame(animate);
        } else {
            canvas.classList.remove('spinning');
            isSpinning = false;
            showResult(targetPrize);
            
            // Haptic feedback
            if (tg.HapticFeedback) {
                tg.HapticFeedback.notificationOccurred('success');
            }
        }
    }
    
    animationId = requestAnimationFrame(animate);
}

// Show result
function showResult(prize) {
    resultPrize.textContent = formatPrize(prize);
    resultDiv.classList.remove('hidden');
    
    // Send result to bot after 3 seconds and close mini app
    setTimeout(() => {
        try {
            // Send prize data to bot
            const data = JSON.stringify({ prize: prize });
            tg.sendData(data);
            
            // Close mini app
            tg.close();
        } catch (error) {
            console.error('Error sending data to bot:', error);
            // If sendData fails, just close
            resultDiv.classList.add('hidden');
        }
    }, 3000);
}

// Check if user can spin
async function checkCanSpin() {
    try {
        loadingDiv.classList.remove('hidden');
        
        const userId = tg.initDataUnsafe?.user?.id;
        
        if (!userId) {
            alert('Ошибка: не удалось получить ID пользователя');
            loadingDiv.classList.add('hidden');
            return false;
        }
        
        const response = await fetch(`/api/can-spin?telegram_id=${userId}`);
        const data = await response.json();
        
        loadingDiv.classList.add('hidden');
        
        if (!data.can_spin) {
            // User already spun
            alreadySpunPrize.textContent = formatPrize(data.prize);
            alreadySpunDiv.classList.remove('hidden');
            spinBtn.style.display = 'none';
            canvas.style.opacity = '0.5';
            return false;
        }
        
        return true;
    } catch (error) {
        console.error('Error checking spin status:', error);
        loadingDiv.classList.add('hidden');
        alert('Ошибка подключения к серверу');
        return false;
    }
}

// Spin the wheel
async function spin() {
    if (isSpinning) return;
    
    const userId = tg.initDataUnsafe?.user?.id;
    
    if (!userId) {
        alert('Ошибка: не удалось получить ID пользователя');
        return;
    }
    
    isSpinning = true;
    spinBtn.disabled = true;
    loadingDiv.classList.remove('hidden');
    
    // Haptic feedback on start
    if (tg.HapticFeedback) {
        tg.HapticFeedback.impactOccurred('medium');
    }
    
    try {
        // Call API to get prize
        const response = await fetch('/api/spin', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                telegram_id: userId
            })
        });
        
        const data = await response.json();
        
        loadingDiv.classList.add('hidden');
        
        if (response.ok) {
            // Animate spin with the prize from server
            animateSpin(data.prize);
        } else {
            isSpinning = false;
            spinBtn.disabled = false;
            
            if (data.error === 'Already spun') {
                alreadySpunPrize.textContent = formatPrize(data.prize);
                alreadySpunDiv.classList.remove('hidden');
                spinBtn.style.display = 'none';
                canvas.style.opacity = '0.5';
            } else {
                alert('Ошибка: ' + (data.error || 'Не удалось прокрутить рулетку'));
            }
        }
    } catch (error) {
        console.error('Error spinning:', error);
        loadingDiv.classList.add('hidden');
        isSpinning = false;
        spinBtn.disabled = false;
        alert('Ошибка подключения к серверу');
    }
}

// Initialize
async function init() {
    // Draw initial wheel
    drawWheel();
    
    // Check if user can spin
    const canSpin = await checkCanSpin();
    
    if (canSpin) {
        // Add spin button event listener
        spinBtn.addEventListener('click', spin);
    }
    
    // Close result on click
    resultDiv.addEventListener('click', () => {
        resultDiv.classList.add('hidden');
    });
}

// Start when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
