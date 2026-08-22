// Psychedelic particle background with Three.js
(function () {
    const canvas = document.getElementById('psychedelic-bg');
    if (!canvas) return;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    camera.position.z = 30;

    // Particles
    const particleCount = 1800;
    const positions = new Float32Array(particleCount * 3);
    const colors = new Float32Array(particleCount * 3);
    const sizes = new Float32Array(particleCount);
    const velocities = [];

    const colorPalette = [
        new THREE.Color('#c084fc'), // purple
        new THREE.Color('#22d3ee'), // cyan
        new THREE.Color('#f472b6'), // pink
        new THREE.Color('#a78bfa'), // violet
        new THREE.Color('#67e8f9'), // light cyan
        new THREE.Color('#e879f9'), // fuchsia
    ];

    for (let i = 0; i < particleCount; i++) {
        const i3 = i * 3;
        positions[i3] = (Math.random() - 0.5) * 80;
        positions[i3 + 1] = (Math.random() - 0.5) * 80;
        positions[i3 + 2] = (Math.random() - 0.5) * 60;

        const color = colorPalette[Math.floor(Math.random() * colorPalette.length)];
        colors[i3] = color.r;
        colors[i3 + 1] = color.g;
        colors[i3 + 2] = color.b;

        sizes[i] = Math.random() * 2.5 + 0.5;

        velocities.push({
            x: (Math.random() - 0.5) * 0.02,
            y: (Math.random() - 0.5) * 0.02,
            z: (Math.random() - 0.5) * 0.01,
            phase: Math.random() * Math.PI * 2
        });
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    geometry.setAttribute('size', new THREE.BufferAttribute(sizes, 1));

    const material = new THREE.PointsMaterial({
        size: 0.35,
        vertexColors: true,
        transparent: true,
        opacity: 0.85,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        sizeAttenuation: true
    });

    const particles = new THREE.Points(geometry, material);
    scene.add(particles);

    // Central glowing orb
    const orbGeometry = new THREE.SphereGeometry(1.8, 32, 32);
    const orbMaterial = new THREE.MeshBasicMaterial({
        color: 0xc084fc,
        transparent: true,
        opacity: 0.15
    });
    const orb = new THREE.Mesh(orbGeometry, orbMaterial);
    scene.add(orb);

    // Soft light rings
    const ringGeo = new THREE.RingGeometry(4, 4.3, 64);
    const ringMat = new THREE.MeshBasicMaterial({
        color: 0x22d3ee,
        transparent: true,
        opacity: 0.12,
        side: THREE.DoubleSide
    });
    const ring1 = new THREE.Mesh(ringGeo, ringMat);
    ring1.rotation.x = Math.PI / 2.2;
    scene.add(ring1);

    const ring2 = new THREE.Mesh(ringGeo, ringMat.clone());
    ring2.material.color.set(0xf472b6);
    ring2.rotation.x = Math.PI / 1.8;
    ring2.scale.setScalar(1.4);
    scene.add(ring2);

    // Mouse interaction
    let mouseX = 0, mouseY = 0;
    let targetX = 0, targetY = 0;

    document.addEventListener('mousemove', (e) => {
        mouseX = (e.clientX / window.innerWidth) * 2 - 1;
        mouseY = -(e.clientY / window.innerHeight) * 2 + 1;
    });

    // Touch
    document.addEventListener('touchmove', (e) => {
        if (e.touches.length > 0) {
            mouseX = (e.touches[0].clientX / window.innerWidth) * 2 - 1;
            mouseY = -(e.touches[0].clientY / window.innerHeight) * 2 + 1;
        }
    }, { passive: true });

    // Animation
    const clock = new THREE.Clock();

    function animate() {
        requestAnimationFrame(animate);
        const t = clock.getElapsedTime();

        // Smooth mouse follow
        targetX += (mouseX * 4 - targetX) * 0.03;
        targetY += (mouseY * 3 - targetY) * 0.03;
        camera.position.x = targetX;
        camera.position.y = targetY;
        camera.lookAt(0, 0, 0);

        // Particle motion
        const pos = geometry.attributes.position.array;
        for (let i = 0; i < particleCount; i++) {
            const i3 = i * 3;
            const v = velocities[i];

            pos[i3] += v.x + Math.sin(t * 0.4 + v.phase) * 0.008;
            pos[i3 + 1] += v.y + Math.cos(t * 0.3 + v.phase) * 0.008;
            pos[i3 + 2] += v.z;

            // Soft boundary wrap
            if (Math.abs(pos[i3]) > 40) pos[i3] *= -0.95;
            if (Math.abs(pos[i3 + 1]) > 40) pos[i3 + 1] *= -0.95;
            if (Math.abs(pos[i3 + 2]) > 30) pos[i3 + 2] *= -0.95;
        }
        geometry.attributes.position.needsUpdate = true;

        // Rotate whole system slowly
        particles.rotation.y = t * 0.03;
        particles.rotation.x = Math.sin(t * 0.1) * 0.08;

        // Orb pulse
        const scale = 1 + Math.sin(t * 1.5) * 0.12;
        orb.scale.setScalar(scale);
        orb.material.opacity = 0.12 + Math.sin(t * 2) * 0.05;

        // Rings
        ring1.rotation.z = t * 0.15;
        ring2.rotation.z = -t * 0.1;

        renderer.render(scene, camera);
    }

    animate();

    // Resize
    window.addEventListener('resize', () => {
        camera.aspect = window.innerWidth / window.innerHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(window.innerWidth, window.innerHeight);
    });
})();
