import {maxFrame, currentFrame, scene, setCurrentFrame, setScene} from './variables'
import {positionReplayObjects} from './replay'
import {addStadium} from './objects'
import {r} from './utils'
import THREE from 'three'
import Detector from './Detector'

let camera
let renderer
let playState = 1

if (!Detector.webgl) {
  Detector.addGetWebGLMessage({
    parent: document.querySelector('.sim-Outer')
  })
}

export function init () {
  setScene(new THREE.Scene())

  renderer = new THREE.WebGLRenderer()
  renderer.setClearColor(0xffffff)
  renderer.setPixelRatio(window.devicePixelRatio)
  renderer.setSize('1248', '702', false)
  renderer.shadowMap.enabled = true

  const container = document.querySelector('.sim-Outer')
  container.appendChild(renderer.domElement)
  renderer.domElement.style.width = '100%'

  camera = new THREE.PerspectiveCamera(2 * Math.atan(8240 / (2 * 5000)) * (180 / Math.PI), 1248 / 702, 1, 30000)
  camera.position.set(0, 0, 5000)
  camera.rotation.set(0, 0, r(90))

  // Add lighting.
  const light = new THREE.DirectionalLight(0xffffff)
  light.castShadow = true
  light.shadow.camera.left = -5000
  light.shadow.camera.right = 5000
  light.shadow.camera.top = 5000
  light.shadow.camera.bottom = -5000
  light.position.set(0, 0, 5000)
  scene.add(light)

  document.querySelector('.sim-Timeline_Outer').addEventListener('mousemove', function (e) {
    if (document.querySelector('.sim-Timeline_Outer') !== e.target) {
      return
    }

    document.querySelector('.sim-Timeline_Cursor').style.left = `${e.offsetX}px`
  })

  document.querySelector('.sim-Timeline_Outer').addEventListener('mousedown', function (e) {
    if (document.querySelector('.sim-Timeline_Outer') !== e.target) {
      return
    }

    // Convert the current position into a frame.
    const percentage = e.offsetX / e.target.offsetWidth

    setCurrentFrame(Math.floor(maxFrame * percentage))
  })

  // Add Play / Pause controls.
  document.querySelector('.sim-Timeline_Controls').addEventListener('mousedown', function (e) {
    const pausedClass = 'sim-Timeline_Controls-paused'

    if (e.target.classList.contains(pausedClass)) {
      e.target.classList.remove(pausedClass)
      playState = 1
    } else {
      e.target.classList.add(pausedClass)
      playState = 0
    }
  })

  addStadium()
  getMaxFPS()
}

function getMaxFPS () {
  var t = []
  var testAnimate = function (now) {
    t.unshift(now)
    if (t.length > 10) {
      var t0 = t.pop()
      var fps = Math.floor(1000 * 10 / (now - t0))
      document.getElementById("fpsSlider").setAttribute("max", fps)
      animate()
    }
    else {
      window.requestAnimationFrame(testAnimate)
    }
  }

  window.requestAnimationFrame(testAnimate)
}

function animate () {
  if (typeof scene === 'undefined') {
    return
  }

  if (typeof currentFrame !== 'undefined' && currentFrame >= 0) {
    positionReplayObjects()

    if (playState === 1) {
      if (currentFrame === maxFrame - 1) {
        setCurrentFrame(0)
      } else {
        setCurrentFrame(currentFrame + 1)
      }
    }
  }

  render()

  const fpsLimit = document.getElementById("fpsSlider").value // Get FPS from slider.
  const timeoutDelay = 1000 / fpsLimit

  setTimeout(() => {
    requestAnimationFrame(animate)
  }, timeoutDelay)
}

function render () {
  renderer.render(scene, camera)
}
