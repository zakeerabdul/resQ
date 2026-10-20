
document.addEventListener('DOMContentLoaded', function () {
  const buttons = document.querySelectorAll('.button');

  buttons.forEach((button) => {
    button.style.transition = 'transform 0.2s ease, box-shadow 0.2s ease';

    button.addEventListener('mouseenter', function () {
      this.style.transform = 'translateY(-2px)';
      this.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.15)';
    });

    button.addEventListener('mouseleave', function () {
      this.style.transform = 'translateY(0)';
      this.style.boxShadow = '';
    });

    button.addEventListener('mousedown', function () {
      this.style.transform = 'scale(0.98)';
    });

    button.addEventListener('mouseup', function () {
      this.style.transform = 'translateY(-2px)';
    });
  });
});
